from netconsole.ui.dialogs.device_form_rules import format_auth_user, validate_device_form_data


def test_validate_device_form_requires_name_and_host():
    assert validate_device_form_data({"name": "", "ip_address": "10.0.0.1", "ssh_enabled": 1, "ssh_port": 22}) == "validation.name_required"
    assert validate_device_form_data({"name": "SW1", "ip_address": "", "ssh_enabled": 1, "ssh_port": 22}) == "validation.host_required"


def test_validate_device_form_requires_ssh_or_telnet():
    assert validate_device_form_data({"name": "SW1", "ip_address": "10.0.0.1", "ssh_enabled": 0, "telnet_enabled": 0}) == "validation.connection_required"


def test_validate_device_form_accepts_ssh_and_telnet_together():
    assert validate_device_form_data({"name": "SW1", "ip_address": "10.0.0.1", "ssh_enabled": 1, "ssh_port": 22, "telnet_enabled": 1, "telnet_port": 23}) is None


def test_credentials_allow_blank_usernames_and_passwords():
    assert validate_device_form_data(
        {
            "name": "SW1",
            "ip_address": "10.0.0.1",
            "ssh_enabled": 1,
            "ssh_port": 22,
            "ssh_username": "",
            "ssh_password": "",
            "telnet_username": "",
            "telnet_password": "",
        }
    ) is None


def test_auth_user_display_rules():
    assert format_auth_user("ssh", "") == "SSH:ssh / Telnet:-"
    assert format_auth_user("", "telnet") == "SSH:- / Telnet:telnet"
    assert format_auth_user("", "") == "SSH:- / Telnet:-"
