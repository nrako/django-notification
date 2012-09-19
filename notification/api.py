from notification.utils import maybe_delay


def can_send(user, notice_type, medium):
    from notification.models import NoticeSetting
    should_send = NoticeSetting.objects.get_for(user, notice_type, medium).send
    return should_send and user.email and user.is_active


def send(*args, **kwargs):
    """
    A basic wrapper around ``notification.tasks.notify``. This honors a global
    flag NOTIFICATION_USE_QUEUE that helps determine whether all calls should
    be queued or not. A per call ``use_queue`` keyword argument can be
    used to always override the default global behavior.
    """
    from notification.tasks import notify
    maybe_delay(notify, *args, **kwargs)
