from django.contrib.auth.models import AnonymousUser

from ..models import NoticeType, ObservedItem


def observe(observed, observer, notice_type_label, signal="post_save"):
    """
    Create a new ObservedItem.

    To be used by applications to register a user as an observer for
    some object.
    """
    notice_type = NoticeType.objects.get(label=notice_type_label)
    observed_item = ObservedItem(
        user=observer, observed_object=observed,
        notice_type=notice_type, signal=signal
    )
    observed_item.save()
    return observed_item


def stop_observing(observed, observer, signal="post_save"):
    """
    Remove an observed item.
    """
    observed_item = ObservedItem.objects.get_for(observed, observer, signal)
    observed_item.delete()


def send_observation_notices_for(observed, signal="post_save",
        extra_context=None):
    """
    Send a notice for each registered user about an observed object.
    """
    if extra_context is None:
        extra_context = {}
    observed_items = ObservedItem.objects.all_for(observed, signal)
    for observed_item in observed_items:
        observed_item.send_notice(extra_context)
    return observed_items


def is_observing(observed, observer, signal="post_save"):
    if isinstance(observer, AnonymousUser):
        return False
    try:
        ObservedItem.objects.get_for(observed, observer, signal)
        return True
    except ObservedItem.DoesNotExist:
        return False
    except ObservedItem.MultipleObjectsReturned:
        return True


def handle_observations(sender, instance, *args, **kw):
    send_observation_notices_for(instance)
