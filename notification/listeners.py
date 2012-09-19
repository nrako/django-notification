from notification.models import ObservedItem


def handle_watch(sender, instance, *args, **kw):
    ObservedItem.objects.notify(instance)
