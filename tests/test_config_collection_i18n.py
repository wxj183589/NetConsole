from netconsole.core import i18n as i18n_module
from netconsole.core.i18n import I18n


def test_config_collection_center_i18n_keys_support_zh_and_en():
    zh = I18n("zh")
    assert i18n_module.locale == "zh"
    assert zh.t("nav.config_collection") == "配置采集中心"
    assert zh.t("config_center.btn.save_config") == "保存配置"
    assert zh.t("config_center.btn.download_config") == "下载配置"
    assert zh.t("config_center.btn.compare_config") == "配置对比"
    assert zh.t("config_center.btn.refresh") == "刷新"
    assert zh.t("config_center.btn.collapse_sidebar") == "收起左侧"
    assert zh.t("config_center.btn.expand_sidebar") == "展开左侧"
    assert zh.t("config_center.btn.select_all") == "全选"
    assert zh.t("config_center.tab.running") == "运行中"
    assert zh.t("config_center.tab.saved") == "已保存"
    assert zh.t("config_center.tab.diff") == "差异"

    en = I18n("en")
    assert i18n_module.locale == "en"
    assert en.t("nav.config_collection") == "Configuration Collection Center"
    assert en.t("config_center.btn.save_config") == "Save Config"
    assert en.t("config_center.btn.download_config") == "Download Config"
    assert en.t("config_center.btn.compare_config") == "Compare Config"
    assert en.t("config_center.btn.refresh") == "Refresh"
    assert en.t("config_center.btn.collapse_sidebar") == "Collapse Sidebar"
    assert en.t("config_center.btn.expand_sidebar") == "Expand Sidebar"
    assert en.t("config_center.btn.select_all") == "Select All"
    assert en.t("config_center.tab.running") == "Running"
    assert en.t("config_center.tab.saved") == "Saved"
    assert en.t("config_center.tab.diff") == "Diff"
