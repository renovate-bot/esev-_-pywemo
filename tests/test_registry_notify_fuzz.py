"""Exercise the NOTIFY subscription http endpoint."""
import contextlib
import string
import sys
import unittest.mock as mock

import atheris
import pytest
import requests
from hypothesis import example, given
from hypothesis import strategies as st

with atheris.instrument_imports():
    from lxml import etree
    import pywemo

from tests.ouimeaux_device.test_device import mocked_requests_get

MOCK_SERVICE_RETURN_VALUES = {
    "bridge": {"GetEndDevicesWithStatus": {}},
    "deviceevent": {
        "GetAttributes": {
            "attributeList": (
                "<attribute>"
                "<name>Switch</name>"
                "<value>1</value>"
                "</attribute>"
            )
        }
    },
    "basicevent": {"GetCrockpotState": {}},
    "insight": {
        "GetInsightParams": {
            "InsightParams": (
                "8|1611105078|2607|0|12416|1209600|328|500|457600|69632638|95"
            )
        }
    },
}


@mock.patch("urllib3.PoolManager.request", side_effect=mocked_requests_get)
def make_device(device_class, *args):
    class WrappedDevice(device_class):
        @property
        def device_type(self) -> str:
            return device_class.__name__

        @property
        def name(self):
            return device_class.__name__

        @name.setter
        def name(self, name):
            pass

        def _check_required_services(self, services):
            for service in self._required_services:
                service_mock = mock.Mock()
                for action, return_value in MOCK_SERVICE_RETURN_VALUES.get(
                    service.name, {}
                ).items():
                    getattr(service_mock, action).return_value = return_value
                self.services[service.name] = service_mock
                setattr(self, service.name, service_mock)

    device = WrappedDevice("http://192.168.1.100:49158/setup.xml")
    device.session.url = "http://127.0.0.1:49158/"
    return device


DEVICES = {
    device.__name__: make_device(device)
    for device in (
        # All subclasses of pywemo.WeMoDevice.
        obj
        for obj in (getattr(pywemo, name) for name in dir(pywemo))
        if isinstance(obj, type)
        and issubclass(obj, pywemo.WeMoDevice)
        and obj != pywemo.WeMoDevice
    )
}
DEVICE_NAMES = sorted(DEVICES.keys())

REGISTRY = pywemo.SubscriptionRegistry()


@contextlib.contextmanager
def registry():
    REGISTRY.start()
    pywemo.subscribe.Subscription.scheduler_active = False
    try:
        yield REGISTRY
    finally:
        pywemo.subscribe.Subscription.scheduler_active = True
        REGISTRY.stop()


@pytest.fixture(scope="module", autouse=True)
def pytest_registry():
    with registry():
        yield


PROPERTY_NAMES = st.one_of(
    st.sampled_from(
        [
            "attributeList",
            "BinaryState",
            "CurrentHumidity",
            "DesiredHumidity",
            "ExpiredFilterTime",
            "FanMode",
            "FilterLife",
            "InsightParams",
            "LongPress",
            "Mode",
            "NoWater",
            "StatusChange",
            "Switch",
            "WaterAdvise",
        ],
    ),
    st.text(alphabet=string.ascii_letters, min_size=1),
)

PROPERTY_VALUES = st.one_of(
    st.none(),
    st.sampled_from(["-1", "0", "1"]),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(
        alphabet=string.ascii_letters
        + string.digits
        + string.punctuation
        + " \t\r\n"
    ),
)


def addAttribute(root, name, value):
    if value is False:
        return
    attr = etree.SubElement(root, name)
    if value is not None:
        attr.text = str(value)


def toXml(properties):
    NS = pywemo.subscribe.NS
    root = etree.Element(f"{NS}propertyset", nsmap={"e": NS[1:-1]})
    for key, value in properties.items():
        prop = etree.SubElement(root, f"{NS}property")
        child = etree.SubElement(prop, key)
        if not isinstance(value, dict):
            if value is not None:
                child.text = str(value)
            continue
        for attrName, attrValue in value.items():
            attr = etree.SubElement(child, "attribute")
            addAttribute(attr, "name", attrName)
            addAttribute(attr, "value", attrValue)
    return etree.tostring(root)


@st.composite
def properties(draw, names=PROPERTY_NAMES, values=PROPERTY_VALUES):
    return {
        **draw(
            st.nothing()
            | st.fixed_dictionaries(
                {
                    "attributeList": st.dictionaries(
                        st.just(False) | names | values,
                        st.just(False) | values,
                    )
                }
            )
        ),
        **draw(st.dictionaries(names, values)),
    }


@given(name=st.sampled_from(DEVICE_NAMES), properties=properties())
# Previous problem cases.
@example(name="Bridge", properties={"StatusChange": "1"})
@example(name="CoffeeMaker", properties={"attributeList": {}})
@example(name="CoffeeMaker", properties={"attributeList": "<"})
@example(name="Insight", properties={"InsightParams": "1"})
def test_notify(name, properties):
    device = DEVICES[name]
    REGISTRY.register(device)
    REGISTRY.on(device, None, lambda d, t, v: d.subscription_update(t, v))
    try:
        response = requests.request(
            "NOTIFY",
            f"http://127.0.0.1:{REGISTRY.port}/sub/basicevent",
            data=toXml(properties),
        )
        assert response.status_code == 200
    finally:
        REGISTRY.unregister(device)


if __name__ == "__main__":
    atheris.Setup(
        sys.argv,
        atheris.instrument_func(test_notify.hypothesis.fuzz_one_input),
    )
    with registry():
        atheris.Fuzz()
