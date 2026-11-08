import argparse
from config import load_settings
from database import Database
from documents import import_csv

def main():
    parser=argparse.ArgumentParser(description="Импорт документов из CSV")
    parser.add_argument("csv_file")
    args=parser.parse_args()
    settings=load_settings()
    db=Database(settings.database)
    try:
        count=import_csv(args.csv_file,db,settings.documents)
        print(f"Импортировано документов: {count}")
    finally: db.close()

if __name__=="__main__": main()
