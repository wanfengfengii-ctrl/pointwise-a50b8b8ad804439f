from .journal import FrozenRevision, ObservationJournal


def freeze_station(journal: ObservationJournal, station: str, revision_id: int) -> int:
    revision = journal.load_revision(revision_id)
    if revision.station != station:
        raise ValueError('recorded revision belongs to a different station')
    return journal.save_frozen(revision.revision_id)


def get_frozen_revision(journal: ObservationJournal, frozen_id: int) -> FrozenRevision:
    return journal.load_frozen(frozen_id)
