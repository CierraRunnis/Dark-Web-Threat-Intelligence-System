from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ExposurePlatform:
    key: str
    label: str
    module: str
    platform_type: str
    homepage_url: str
    login_url: str
    domains: tuple[str, ...]
    requires_login: bool = False
    discovery_only: bool = False
    success_indicators: tuple[str, ...] = ()
    login_indicators: tuple[str, ...] = ()


PLATFORMS: dict[str, ExposurePlatform] = {
    "baidu_wenku": ExposurePlatform(
        key="baidu_wenku",
        label="百度文库",
        module="document_exposure",
        platform_type="document_library",
        homepage_url="https://wenku.baidu.com/",
        login_url="https://wenku.baidu.com/",
        domains=("wenku.baidu.com",),
        requires_login=True,
        success_indicators=("文库", "wenku", "百度账号"),
        login_indicators=("登录", "扫码登录", "百度账号登录", "passport.baidu.com"),
    ),
    "docin": ExposurePlatform(
        key="docin",
        label="豆丁",
        module="document_exposure",
        platform_type="document_library",
        homepage_url="https://www.docin.com/",
        login_url="https://www.docin.com/",
        domains=("docin.com", "www.docin.com"),
        requires_login=False,
        success_indicators=("docin", "豆丁"),
        login_indicators=("登录", "docin登录"),
    ),
    "doc88": ExposurePlatform(
        key="doc88",
        label="道客巴巴",
        module="document_exposure",
        platform_type="document_library",
        homepage_url="https://www.doc88.com/",
        login_url="https://www.doc88.com/",
        domains=("doc88.com", "www.doc88.com"),
        requires_login=False,
        success_indicators=("doc88", "道客巴巴"),
        login_indicators=("登录", "会员登录"),
    ),
    "book118": ExposurePlatform(
        key="book118",
        label="原创力文档",
        module="document_exposure",
        platform_type="document_library",
        homepage_url="https://max.book118.com/",
        login_url="https://max.book118.com/",
        domains=("book118.com", "max.book118.com"),
        requires_login=False,
        success_indicators=("book118", "原创力文档"),
        login_indicators=("登录", "注册登录"),
    ),
    "iask_share": ExposurePlatform(
        key="iask_share",
        label="爱问共享资料",
        module="document_exposure",
        platform_type="document_library",
        homepage_url="https://ishare.iask.sina.com.cn/",
        login_url="https://ishare.iask.sina.com.cn/",
        domains=("ishare.iask.sina.com.cn", "iask.sina.com.cn"),
        requires_login=False,
        success_indicators=("爱问共享资料", "iask"),
        login_indicators=("登录", "新浪登录"),
    ),
    "xiaobaipan": ExposurePlatform(
        key="xiaobaipan",
        label="小白盘",
        module="document_exposure",
        platform_type="netdisk_search",
        homepage_url="https://www.xiaobaipan.com/",
        login_url="https://www.xiaobaipan.com/",
        domains=("xiaobaipan.com", "www.xiaobaipan.com"),
        discovery_only=True,
    ),
    "pansou": ExposurePlatform(
        key="pansou",
        label="PanSou",
        module="document_exposure",
        platform_type="netdisk_search",
        homepage_url="https://github.com/fish2018/pansou",
        login_url="https://github.com/fish2018/pansou",
        domains=(),
        discovery_only=True,
    ),
    "panhub": ExposurePlatform(
        key="panhub",
        label="PanHub",
        module="document_exposure",
        platform_type="netdisk_search",
        homepage_url="https://github.com/wu529778790/panhub.shenzjd.com",
        login_url="https://github.com/wu529778790/panhub.shenzjd.com",
        domains=("panhub.shenzjd.com",),
        discovery_only=True,
    ),
    "pikasoo": ExposurePlatform(
        key="pikasoo",
        label="皮卡搜索",
        module="document_exposure",
        platform_type="netdisk_search",
        homepage_url="https://www.pikasoo.top/",
        login_url="https://www.pikasoo.top/",
        domains=("pikasoo.top", "www.pikasoo.top"),
        discovery_only=True,
    ),
    "lzpanx": ExposurePlatform(
        key="lzpanx",
        label="懒盘搜索",
        module="document_exposure",
        platform_type="netdisk_search",
        homepage_url="https://www.lzpanx.com/",
        login_url="https://www.lzpanx.com/",
        domains=("lzpanx.com", "www.lzpanx.com"),
        discovery_only=True,
    ),
    "esoua": ExposurePlatform(
        key="esoua",
        label="爱搜",
        module="document_exposure",
        platform_type="netdisk_search",
        homepage_url="https://www.esoua.com/",
        login_url="https://www.esoua.com/",
        domains=("esoua.com", "www.esoua.com"),
        discovery_only=True,
    ),
    "xiaobudian": ExposurePlatform(
        key="xiaobudian",
        label="小不点搜索",
        module="document_exposure",
        platform_type="netdisk_search",
        homepage_url="https://www.xiaoso.net/",
        login_url="https://www.xiaoso.net/",
        domains=("xiaoso.net", "www.xiaoso.net"),
        discovery_only=True,
    ),
    "lingfengyun": ExposurePlatform(
        key="lingfengyun",
        label="凌风云",
        module="document_exposure",
        platform_type="netdisk_search",
        homepage_url="https://www.lingfengyun.com/",
        login_url="https://www.lingfengyun.com/",
        domains=("lingfengyun.com", "www.lingfengyun.com"),
        discovery_only=True,
    ),
    "dalipan": ExposurePlatform(
        key="dalipan",
        label="大力盘",
        module="document_exposure",
        platform_type="netdisk_search",
        homepage_url="https://www.dalipan.com/",
        login_url="https://www.dalipan.com/",
        domains=("dalipan.com", "www.dalipan.com"),
        discovery_only=True,
    ),
    "pandashi": ExposurePlatform(
        key="pandashi",
        label="盘大师",
        module="document_exposure",
        platform_type="netdisk_search",
        homepage_url="https://www.pandashi8.com/",
        login_url="https://www.pandashi8.com/",
        domains=("pandashi8.com", "www.pandashi8.com"),
        discovery_only=True,
    ),
    "panyq": ExposurePlatform(
        key="panyq",
        label="盘友圈",
        module="document_exposure",
        platform_type="netdisk_search",
        homepage_url="https://panyq.com/",
        login_url="https://panyq.com/",
        domains=("panyq.com", "www.panyq.com"),
        discovery_only=True,
    ),
    "baidupan_share": ExposurePlatform(
        key="baidupan_share",
        label="百度网盘",
        module="document_exposure",
        platform_type="netdisk_share",
        homepage_url="https://pan.baidu.com/",
        login_url="https://pan.baidu.com/",
        domains=("pan.baidu.com",),
        requires_login=True,
        success_indicators=("百度网盘", "pan.baidu.com", "文件", "分享"),
        login_indicators=("登录", "提取码", "账号登录", "扫码登录"),
    ),
    "aliyundrive_share": ExposurePlatform(
        key="aliyundrive_share",
        label="阿里云盘",
        module="document_exposure",
        platform_type="netdisk_share",
        homepage_url="https://www.alipan.com/",
        login_url="https://www.alipan.com/",
        domains=("www.alipan.com", "alipan.com", "aliyundrive.com", "www.aliyundrive.com"),
        requires_login=True,
        success_indicators=("阿里云盘", "alipan", "文件"),
        login_indicators=("登录", "扫码登录", "手机号登录"),
    ),
    "quark_share": ExposurePlatform(
        key="quark_share",
        label="夸克网盘",
        module="document_exposure",
        platform_type="netdisk_share",
        homepage_url="https://pan.quark.cn/",
        login_url="https://pan.quark.cn/",
        domains=("pan.quark.cn",),
        requires_login=True,
        success_indicators=("夸克", "quark", "文件"),
        login_indicators=("登录", "扫码登录", "手机号登录"),
    ),
    "tianyi_share": ExposurePlatform(
        key="tianyi_share",
        label="天翼云盘",
        module="document_exposure",
        platform_type="netdisk_share",
        homepage_url="https://cloud.189.cn/",
        login_url="https://cloud.189.cn/",
        domains=("cloud.189.cn",),
        requires_login=True,
        success_indicators=("天翼云盘", "cloud.189.cn", "文件"),
        login_indicators=("登录", "扫码登录", "手机号登录"),
    ),
    "pan123_share": ExposurePlatform(
        key="pan123_share",
        label="123云盘",
        module="document_exposure",
        platform_type="netdisk_share",
        homepage_url="https://www.123684.com/",
        login_url="https://www.123684.com/",
        domains=("123684.com", "www.123684.com", "123pan.com", "www.123pan.com"),
        requires_login=False,
        success_indicators=("123云盘", "123pan", "文件"),
        login_indicators=("登录", "手机号登录"),
    ),
    "onedrive_share": ExposurePlatform(
        key="onedrive_share",
        label="OneDrive",
        module="document_exposure",
        platform_type="netdisk_share",
        homepage_url="https://onedrive.live.com/",
        login_url="https://onedrive.live.com/",
        domains=("1drv.ms", "onedrive.live.com", "sharepoint.com"),
        requires_login=False,
        success_indicators=("onedrive", "sharepoint", "download", "文件"),
        login_indicators=("sign in", "登录", "microsoft account"),
    ),
    "xunlei_share": ExposurePlatform(
        key="xunlei_share",
        label="迅雷云盘",
        module="document_exposure",
        platform_type="netdisk_share",
        homepage_url="https://pan.xunlei.com/",
        login_url="https://pan.xunlei.com/",
        domains=("pan.xunlei.com", "drive.xunlei.com"),
        requires_login=False,
        success_indicators=("迅雷", "xunlei", "文件"),
        login_indicators=("登录", "手机号登录"),
    ),
    "uc_share": ExposurePlatform(
        key="uc_share",
        label="UC网盘",
        module="document_exposure",
        platform_type="netdisk_share",
        homepage_url="https://drive.uc.cn/",
        login_url="https://drive.uc.cn/",
        domains=("drive.uc.cn", "pc-api.uc.cn"),
        requires_login=False,
        success_indicators=("uc网盘", "drive.uc.cn", "文件"),
        login_indicators=("登录", "手机号登录"),
    ),
    "mobile_share": ExposurePlatform(
        key="mobile_share",
        label="移动云盘",
        module="document_exposure",
        platform_type="netdisk_share",
        homepage_url="https://caiyun.139.com/",
        login_url="https://caiyun.139.com/",
        domains=("caiyun.139.com", "yun.139.com"),
        requires_login=False,
        success_indicators=("移动云盘", "139.com", "文件"),
        login_indicators=("登录", "手机号登录"),
    ),
    "pan115_share": ExposurePlatform(
        key="pan115_share",
        label="115网盘",
        module="document_exposure",
        platform_type="netdisk_share",
        homepage_url="https://115.com/",
        login_url="https://115.com/",
        domains=("115.com", "115cdn.com", "anxia.com"),
        requires_login=False,
        success_indicators=("115", "文件", "分享"),
        login_indicators=("登录", "手机号登录"),
    ),
    "pikpak_share": ExposurePlatform(
        key="pikpak_share",
        label="PikPak",
        module="document_exposure",
        platform_type="netdisk_share",
        homepage_url="https://mypikpak.com/",
        login_url="https://mypikpak.com/",
        domains=("mypikpak.com", "drive.mypikpak.com"),
        requires_login=False,
        success_indicators=("pikpak", "文件", "download"),
        login_indicators=("sign in", "登录"),
    ),
    "github": ExposurePlatform(
        key="github",
        label="GitHub",
        module="code_monitoring",
        platform_type="code_repository",
        homepage_url="https://github.com/",
        login_url="https://github.com/login",
        domains=("github.com", "www.github.com"),
        requires_login=True,
        success_indicators=("github", "repositories", "code search"),
        login_indicators=("sign in", "登录", "session expired"),
    ),
    "gitlab": ExposurePlatform(
        key="gitlab",
        label="GitLab",
        module="code_monitoring",
        platform_type="code_repository",
        homepage_url="https://gitlab.com/",
        login_url="https://gitlab.com/users/sign_in",
        domains=("gitlab.com", "www.gitlab.com"),
        requires_login=True,
        success_indicators=("gitlab", "projects", "search"),
        login_indicators=("sign in", "登录", "gitlab sign in"),
    ),
    "gitee": ExposurePlatform(
        key="gitee",
        label="Gitee",
        module="code_monitoring",
        platform_type="code_repository",
        homepage_url="https://gitee.com/",
        login_url="https://gitee.com/login",
        domains=("gitee.com", "search.gitee.com", "www.gitee.com"),
        requires_login=True,
        success_indicators=("gitee", "仓库", "代码"),
        login_indicators=("登录", "立即登录", "扫码登录"),
    ),
}


SEARCH_ENGINES: tuple[ExposurePlatform, ...] = (
    ExposurePlatform(
        key="baidu_search",
        label="百度搜索",
        module="document_exposure",
        platform_type="search_engine",
        homepage_url="https://www.baidu.com/",
        login_url="https://www.baidu.com/",
        domains=("baidu.com", "www.baidu.com"),
    ),
    ExposurePlatform(
        key="bing_search",
        label="Bing",
        module="document_exposure",
        platform_type="search_engine",
        homepage_url="https://www.bing.com/",
        login_url="https://www.bing.com/",
        domains=("bing.com", "www.bing.com"),
    ),
    ExposurePlatform(
        key="so360_search",
        label="360搜索",
        module="document_exposure",
        platform_type="search_engine",
        homepage_url="https://www.so.com/",
        login_url="https://www.so.com/",
        domains=("so.com", "www.so.com"),
    ),
)


def list_exposure_platforms(
    *,
    include_discovery_only: bool = True,
    include_netdisk_share: bool = True,
    module: str | None = None,
) -> list[ExposurePlatform]:
    platforms: list[ExposurePlatform] = []
    for key in sorted(PLATFORMS):
        platform = PLATFORMS[key]
        if module and platform.module != str(module).strip():
            continue
        if not include_discovery_only and platform.discovery_only:
            continue
        if not include_netdisk_share and platform.platform_type == "netdisk_share":
            continue
        platforms.append(platform)
    return platforms


def list_session_manageable_platforms(module: str | None = None) -> list[ExposurePlatform]:
    return [
        platform
        for platform in list_exposure_platforms(
            include_discovery_only=False,
            include_netdisk_share=False,
            module=module,
        )
        if platform.requires_login
    ]


def get_exposure_platform(platform: str) -> ExposurePlatform:
    try:
        return PLATFORMS[str(platform or "").strip()]
    except KeyError as exc:
        known = ", ".join(sorted(PLATFORMS))
        raise ValueError(f"unknown exposure platform '{platform}', available platforms: {known}") from exc


def platform_from_url(url: str) -> ExposurePlatform | None:
    host = urlparse(str(url or "")).netloc.lower().strip()
    if not host:
        return None
    for platform in PLATFORMS.values():
        if any(host == domain or host.endswith(f".{domain}") for domain in platform.domains):
            return platform
    return None


def monitored_domains(module: str | None = None) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for platform in PLATFORMS.values():
        if module and platform.module != str(module).strip():
            continue
        for domain in platform.domains:
            normalized = str(domain).strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                values.append(normalized)
    return tuple(values)
