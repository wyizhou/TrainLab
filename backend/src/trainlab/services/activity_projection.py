from trainlab.db.models.activity import Activity, ActivityImport


def effective_activity_title(activity: Activity, imported: ActivityImport) -> str:
    return imported.title_override if imported.title_override is not None else activity.title
