# H3C Jinja2 命令模板

在任务中心选择「创建设备任务」和「自定义命令采集」，填写模板、参数定义和参数值，再预览命令。提交时，后端重新渲染并校验最终命令，设备只执行白名单中的查询。

## 只读采集

```jinja2
{# 查询交换机指定接口的光模块诊断信息 #}
display transceiver diagnosis interface {{ interface }}
```

参数定义

```json
{
  "interface": {
    "type": "interface",
    "required": true,
    "description": "设备接口名称"
  }
}
```

参数值

```json
{"interface": "GigabitEthernet1/0/1"}
```

支持的参数类型为 `string`、`interface`、`integer`、`boolean`、`list` 和 `object`。可选参数可以设置默认值。模板支持注释、变量、循环、条件，以及 `default`、`join`、`lower`、`upper` 和 `trim`。渲染使用 Jinja2 Sandbox 和 `StrictUndefined`。参数中的换行和控制字符会导致校验失败。

## 配置命令预览

```jinja2
{#
预览 VLAN 命令。
变量 vlans 使用 list 类型。
#}
{% for vlan in vlans %}
vlan {{ vlan.id }}
{% if vlan.name %}
 name {{ vlan.name | lower }}
{% endif %}
 quit
{% endfor %}
save force
```

模板可以预览配置变更命令。此类结果标记为 `configuration_change`，只有通过逐条白名单校验的结果可作为只读采集任务提交。最多提交八条查询命令。

## 执行与结果

设备任务使用现有 Job Center。每次手动执行的 Task ID 同时用作 Run ID，失败重试生成新的 Run ID 并记录原任务 ID。设备目标按当前局点和设备 UUID 解析。每个任务最多四台设备并行连接，同一批次内每台设备按顺序执行命令。

配置收集和备份复用配置中心的 running/saved 快照。光衰任务复用设备光模块采集，按本次采集 ID 获取结果。LLDP、诊断、版本和自定义命令的回显进入逐设备结果。命令结果会脱敏并限制长度。任务状态、进度和事件保存在现有任务数据库，可从「应用日志与安全维护」的「任务日志」通过同一 ID 查询。

## 局点模板库

填写模板名称、分类、适用设备及命令类型后，可以保存并在当前局点重复使用。修改模板或启停都会生成新版本。通过版本历史载入先前内容并保存，可以恢复为最新版本。复制模板会创建新的模板记录。

运行已保存模板时，预览校验模板版本和输入参数。提交时重新计算校验值，通过后才生成任务。版本变更、停用和参数修改需要重新预览。已保存模板的失败设备可在任务中心使用当前版本重新发起。

当前交付覆盖手动只读采集、模板库和配置变更命令预览。模板文件导入导出、计划任务、持续监控、可确认的配置下发、升级计划和日志推送仍待交付。LLDP 任务结果尚未成为组织自动归组的 Current 数据源。
