"""
This module defines the JSON schemas for validating IPC commands
sent to the mfc_daemon.
"""

from jsonschema import ValidationError, validate

# Base schema for any command, requiring an 'action' field.
base_command_schema = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
    },
    "required": ["action"],
}

# Schema for the 'add_mfc_rule' command payload.
add_mfc_rule_schema = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "format": "ipv4"},
        "group": {"type": "string", "format": "ipv4"},
        "iif": {"type": "string", "minLength": 1},
        "oifs": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
            "uniqueItems": True,
        },
        "dry_run": {"type": "boolean"},
    },
    "required": ["source", "group", "iif", "oifs"],
}

# Schema for the 'del_mfc_rule' command payload.
del_mfc_rule_schema = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "format": "ipv4"},
        "group": {"type": "string", "format": "ipv4"},
        "dry_run": {"type": "boolean"},
    },
    "required": ["source", "group"],
}


class CommandValidator:
    """A validator for daemon commands."""

    def __init__(self):
        self.validators = {
            "ADD_MFC": self.validate_add_mfc,
            "DEL_MFC": self.validate_del_mfc,
            "SHOW": self.validate_show,
        }

    def validate(self, command_data):
        """
        Validates a command against the base schema and its specific schema.

        Args:
            command_data (dict): The command data received from the IPC.

        Returns:
            tuple(dict, str|None): A tuple of (validated_payload, error_message).
                                   If validation fails, payload is None.
        """
        try:
            validate(instance=command_data, schema=base_command_schema)
            action = command_data.get("action")
            payload = command_data.get("payload", {})

            validator_func = self.validators.get(action)
            if not validator_func:
                return None, f"Unknown action: {action}"

            return validator_func(payload)

        except ValidationError as e:
            return None, f"Invalid command structure: {e.message}"

    def validate_add_mfc(self, payload):
        """Validates the payload for an ADD_MFC command."""
        try:
            validate(instance=payload, schema=add_mfc_rule_schema)
            return payload, None
        except ValidationError as e:
            return None, f"Invalid ADD_MFC payload: {e.message}"

    def validate_del_mfc(self, payload):
        """Validates the payload for a DEL_MFC command."""
        try:
            validate(instance=payload, schema=del_mfc_rule_schema)
            return payload, None
        except ValidationError as e:
            return None, f"Invalid DEL_MFC payload: {e.message}"

    def validate_show(self, payload):
        """'SHOW' command has no payload to validate."""
        return payload, None
