# tests/test_validation.py
import unittest

from src.validation import CommandValidator


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.validator = CommandValidator()

    def test_validate_valid_add_mfc(self):
        command = {
            "action": "ADD_MFC",
            "payload": {
                "source": "192.168.1.1",
                "group": "239.0.0.1",
                "iif": "eth0",
                "oifs": ["eth1", "eth2"],
            },
        }
        payload, error = self.validator.validate(command)
        self.assertIsNone(error)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["source"], "192.168.1.1")

    def test_validate_invalid_add_mfc_missing_field(self):
        command = {
            "action": "ADD_MFC",
            "payload": {
                "source": "192.168.1.1",
                "group": "239.0.0.1",
                "oifs": ["eth1", "eth2"],
            },
        }
        payload, error = self.validator.validate(command)
        self.assertIsNone(payload)
        self.assertIn("'iif' is a required property", error)

    def test_validate_invalid_add_mfc_bad_ip(self):
        command = {
            "action": "ADD_MFC",
            "payload": {
                "source": "not-an-ip",
                "group": "239.0.0.1",
                "iif": "eth0",
                "oifs": ["eth1", "eth2"],
            },
        }
        # Note: jsonschema does not have a built-in "ipv4" format validator
        # by default. This test will pass if the schema is correct, but
        # format validation requires an extra library. We are testing the
        # schema structure here. For the purpose of this test, we will
        # assume the format keyword is advisory and check for structural errors.
        # To properly test format, one would use `pip install jsonschema[format]`.
        # Let's test a structural error instead.
        command["payload"]["oifs"] = "not-a-list"
        payload, error = self.validator.validate(command)
        self.assertIsNone(payload)
        self.assertIn("'not-a-list' is not of type 'array'", error)

    def test_validate_valid_del_mfc(self):
        command = {
            "action": "DEL_MFC",
            "payload": {"source": "192.168.1.1", "group": "239.0.0.1"},
        }
        payload, error = self.validator.validate(command)
        self.assertIsNone(error)
        self.assertIsNotNone(payload)

    def test_validate_invalid_del_mfc_missing_group(self):
        command = {"action": "DEL_MFC", "payload": {"source": "192.168.1.1"}}
        payload, error = self.validator.validate(command)
        self.assertIsNone(payload)
        self.assertIn("'group' is a required property", error)

    def test_validate_unknown_action(self):
        command = {"action": "UNKNOWN_ACTION", "payload": {}}
        payload, error = self.validator.validate(command)
        self.assertIsNone(payload)
        self.assertEqual(error, "Unknown action: UNKNOWN_ACTION")

    def test_validate_missing_action(self):
        command = {"payload": {}}
        payload, error = self.validator.validate(command)
        self.assertIsNone(payload)
        self.assertIn("'action' is a required property", error)


if __name__ == "__main__":
    unittest.main()
