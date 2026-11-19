"""Route project data to the class-utilization SQL Server database."""


class GitAMDatabaseRouter:
    """Keep project models off the local dummy/default database."""

    database = 'CLASSUTILIZATION'

    routed_apps = {
        'admin',
        'auth',
        'contenttypes',
        'usermanagement',
        'workspace',
    }

    def db_for_read(self, model, **hints):
        if model._meta.app_label in self.routed_apps:
            return self.database
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label in self.routed_apps:
            return self.database
        return None

    def allow_relation(self, obj1, obj2, **hints):
        project_objects = {
            obj1._state.db,
            obj2._state.db,
        }
        if self.database in project_objects:
            return project_objects <= {self.database, None}
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.routed_apps:
            # Allow schema on the SQL Server DB and a local copy in 'default'.
            return db in (self.database, 'default')
        return None
