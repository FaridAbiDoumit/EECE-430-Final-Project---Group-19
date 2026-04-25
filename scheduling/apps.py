from django.apps import AppConfig


def _configure_sqlite_connection(connection, **kwargs):
    if connection.vendor != 'sqlite':
        return

    try:
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute('PRAGMA synchronous=NORMAL;')
            cursor.execute('PRAGMA busy_timeout=5000;')
    except Exception:
        # Best-effort tuning for local demo concurrency.
        pass


class SchedulingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'scheduling'

    def ready(self):
        from django.db.backends.signals import connection_created

        connection_created.connect(
            _configure_sqlite_connection,
            dispatch_uid='scheduling.configure_sqlite_connection',
        )
