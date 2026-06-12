# Device Management

The first NetConsole desktop stage only implements device management.

Supported workflows:

- Device list
- Add device
- Edit device
- Delete device
- Refresh
- Search by name, sysname, IP address, station, tags, and remark
- Filter by vendor and device type
- Import `.csv`
- Export `.csv`
- Export CSV template

The CSV template is a simplified Chinese-header file for manual entry and includes one example device row. The CSV export is a complete English-header file for backup and re-import.

The add/edit dialog stores SSH and Telnet connection settings. A device can enable either or both protocols.

SNMP fields are reserved configuration fields only. SNMPv1, SNMPv2c, and SNMPv3 can be enabled independently. SNMP collection is not implemented in this stage.

The UI text is provided by `netconsole/core/i18n.py` and currently supports `zh_CN` and `en_US`.
