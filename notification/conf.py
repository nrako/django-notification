from django.conf import settings  # noqa
from django.utils.translation import ugettext_lazy as _

from appconf import AppConf


class NotificationConf(AppConf):
    MEDIA = (
        ("1", _("Email")),
    )

    # how spam-sensitive is the medium
    MEDIA_DEFAULTS = {
        "1": 2,  # email
    }

    LANGUAGE_MODULE = False

    USE_QUEUE = False

    USE_PYNLINER = False
