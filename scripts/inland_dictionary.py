"""Augment the installed GDAL dictionaries with OpenCPN's inland feature definitions."""
import csv
from pathlib import Path
import shutil
import sys


def install(source, target):
    target.mkdir(parents=True, exist_ok=True)
    upstream = Path(__file__).resolve().parents[1] / 'portrayal/upstream'
    for original in source.glob('s57*.csv'):
        extra = upstream / original.name
        if not extra.is_file():
            shutil.copyfile(original, target / original.name)
            continue
        with original.open(encoding='utf-8-sig') as src, extra.open(encoding='utf-8-sig') as additions:
            header = src.readline()
            rows = {int(row[0]):row for row in csv.reader(src) if row and row[0].isdigit() and int(row[0])>0}
            for row in csv.reader(additions):
                if row and row[0].isdigit() and 17000 <= int(row[0]) < 19000:
                    rows[int(row[0])] = row
        with (target/original.name).open('w',newline='') as dst:
            dst.write(header)
            writer = csv.writer(dst)
            for row in rows.values():
                # GeoPackage and SQLite identifiers are case-insensitive.
                if original.name == 's57objectclasses.csv':
                    if row[2].islower():
                        row[2] = 'i_' + row[2]
                    # GDAL 3.8 writes NATF by field name. National text can
                    # occur on classes whose maritime definition omits it.
                    fields = [field for column in row[3:6] for field in column.split(';') if field]
                    fields.extend(['OBJNAM','INFORM','NINFOM','NOBJNM','NPLDST','$NTXST','NTXTDS'])
                    row[3:6] = [';'.join(dict.fromkeys(fields)) + ';','','']
                writer.writerow(row)


if __name__ == '__main__':
    install(Path(sys.argv[1]), Path(sys.argv[2]))
