"""One guard for every command that writes fictional identities or histories (guide 07 §11).

development/test: allowed with DEMO_MODE=true. demo (hosted fictional demo): allowed only with the
deliberate `--hosted-demo` opt-in. production or DEMO_MODE=false: always refused.
"""

from app.core.config import get_settings


class ProvisioningRefused(RuntimeError):
    pass


def check_provisioning(hosted_demo: bool = False) -> None:
    settings = get_settings()
    if settings.APP_ENV == "production":
        raise ProvisioningRefused("refusing to provision fictional data with APP_ENV=production")
    if not settings.DEMO_MODE:
        raise ProvisioningRefused("refusing to provision fictional data with DEMO_MODE=false")
    if settings.APP_ENV == "demo" and not hosted_demo:
        raise ProvisioningRefused(
            "APP_ENV=demo is the hosted demo: pass --hosted-demo to provision deliberately"
        )
    if settings.APP_ENV != "demo" and hosted_demo:
        raise ProvisioningRefused("--hosted-demo is only valid with APP_ENV=demo")
