from notification.conf import settings


def can_queue(func, **kwargs):
    """
    Returns a boolean describing if func should be passed through the queueing
    infrastructure based on the ``USE_QUEUE`` setting.

    >>> can_queue(task_func)
    True
    """
    use_queue = kwargs.pop('use_queue', settings.NOTIFICATION_USE_QUEUE)
    if not use_queue:
        return False
    elif use_queue is True:
        return True
    elif '%s.%s' % (func.__module__, func.__name__) in settings.NOTIFICATION_USE_QUEUE:
        return True
    return False


def maybe_delay(func, *args, **kwargs):
    if can_queue(func, **kwargs):
        return func.delay(*args, **kwargs)
    return func(*args, **kwargs)
