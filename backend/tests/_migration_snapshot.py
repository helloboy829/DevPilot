"""Snapshot rows using the schema that is actually present in the database."""

from sqlalchemy import MetaData, Table, inspect, select


def snapshot_rows(connection, tables):
    names = set(inspect(connection).get_table_names())
    snapshots = {}
    for source in tables:
        if source.name not in names:
            continue
        reflected = Table(source.name, MetaData(), autoload_with=connection)
        statement = select(reflected)
        if reflected.primary_key.columns:
            statement = statement.order_by(*reflected.primary_key.columns)
        snapshots[source.name] = [{key: value for key, value in row.items() if not (source.name == "evaluation_projects" and key == "result_revision")} for row in connection.execute(statement).mappings()]
    return snapshots
