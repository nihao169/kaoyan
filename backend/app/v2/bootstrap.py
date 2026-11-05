"""Initialize required catalog configuration without shared demo credentials."""
from sqlalchemy import select
from ..db import SessionLocal
from .. import models as m


if __name__ == '__main__':
    with SessionLocal.begin() as db:
        if not db.scalar(select(m.Subject.id).where(m.Subject.code == 'politics')):
            db.add(m.Subject(code='politics', name='考研政治'))
