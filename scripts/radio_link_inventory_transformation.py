import logging
import re
import numpy as np
import pandas as pd
import sqlalchemy as db
from sqlalchemy_utils import create_database, database_exists
from functools import wraps
import configparser

logging.basicConfig(filename='./log.log', format="%(levelname)s:%(asctime)s - %(message)s",
                    level=logging.DEBUG, datefmt="%d-%b-%y %H:%M:%S")

def log_function_call(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        logging.info(f"Calling function: {func.__name__}")
        return func(*args, **kwargs)
    return wrapper

@log_function_call
def establish_connection(username, password, database, host='localhost', port=3306):
    try:
        db_conn = db.create_engine(
            f"mariadb+pymysql://{username}:{password}@{host}/{database}")
        if not database_exists(db_conn.url):
            create_database(db_conn.url)
        connection = db_conn.connect()
        logging.info(f"Connected to DB.")
        return db_conn, connection
    except Exception as e:
        logging.error("Failed to connect to DB.")
        raise e

@log_function_call
def create_table(db_conn, table_name, fields):
    metadata = db.MetaData()
    columns = [db.Column(field_name, field_type) for field_name, field_type in fields]
    ne_inventory_table = db.Table(table_name, metadata, *columns)
    metadata.create_all(db_conn, checkfirst=True)
    logging.info(f"Database table '{table_name}' has been created")

@log_function_call
def read_fields_from_ini(filename):
    config = configparser.ConfigParser()
    config.read(filename)

    database_section = config['Database']
    username = database_section['username']
    password = database_section['password']
    database = database_section['database']

    table_section = config['Table']
    table_name = table_section['table_name']

    fields = []
    type_map = {
        'String': db.String,
        'Integer': db.Integer,
        'Float': db.Float,
        'DateTime': db.DateTime
    }
    for field_name, field_type_str in config.items('Fields'):
        field_type_parts = field_type_str.split('(')
        field_type_name = field_type_parts[0]
        field_type_args = ()
        if len(field_type_parts) > 1:
            field_type_args = tuple(map(int, re.findall(r'\d+', field_type_parts[1])))
        field_type = type_map.get(field_type_name)
        if field_type is None:
            logging.error(f"Unknown field type: {field_type_name}")
            continue
        fields.append((field_name, field_type(*field_type_args)))

    return username, password, database, table_name, fields

@log_function_call
def load_radio_link_values(db_conn, connection, table_name):
    try:
        # Data Reading and Manipulation
        input_file = pd.read_excel("../data_sheets/Radio_Link_Inventory.xls", skiprows=3, usecols=['Part Number', 'Radio Link', 'User Label', 'Tx Frequency (Ghz)', 'NE ID', 'NE Name','Link Distance(km)', 'Rx Frequency (Ghz)', 'Max Capacity (Mbps)', 'Min Capacity (Mbps)','Mnemonic','In Lag'])
        input_file = input_file.rename(
            columns={"Radio Link": "radioLink", "Link Distance(km)": "linkDistance(km)", "NE ID": "neId","NE Name": "neName",
             "User Label": "userLabel", "Mnemonic": "mnemonic", "Part Number": "partNumber", "Tx Frequency (Ghz)": "TxFrequency(Ghz)", "Rx Frequency (Ghz)": "RxFrequency(Ghz)", "Max Capacity (Mbps)": "maxCapacity(Mbps)", "Min Capacity (Mbps)": "minCapacity(Mbps)","In Lag": "inLag"})

        band_file = pd.read_excel("../data_sheets/band.xlsx", usecols=['Band (GHz)', 'From (MHz)', 'To (MHz)'])

        # Function to get band for a given frequency
        def get_band(frequency):
            for index, row in band_file.iterrows():
                if row['From (MHz)'] <= frequency * 1000 <= row['To (MHz)']:
                    return row['Band (GHz)']
            return None

        # Add new columns for band values for Tx and Rx frequencies
        input_file['TxBand'] = input_file['TxFrequency(Ghz)'].apply(get_band)
        input_file['RxBand'] = input_file['RxFrequency(Ghz)'].apply(get_band)

        # Define the site IDs that should have 'other' as the Region
        other_site_ids = ['10.99.94.232', '10.99.94.233', '10.99.94.234']

        # Categorize 'neName' values based on certain patterns
        input_file['Region'] = input_file['neId'].apply(lambda x: 'other' if x in other_site_ids else 'AUH')

        # Replace NaN values with None (which translates to NULL in SQL)
        input_file = input_file.where(pd.notnull(input_file), 'N/A')

        input_file.to_sql(table_name, db_conn, if_exists='replace', index=False)
        connection.close()
        db_conn.dispose()
    except Exception as e:
        logging.error(f"An error occurred during data processing: {str(e)}")
        return
    finally:
        if 'connection' in locals():
            connection.close()
        if 'db_conn' in locals():
            db_conn.dispose()


@log_function_call
def main():
    try:
        username, password, database, table_name, fields = read_fields_from_ini('config.ini')
        db_conn, connection = establish_connection(username, password, database)
        create_table(db_conn, table_name, fields)
        load_radio_link_values(db_conn, connection,table_name)
    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")

if __name__ == '__main__':
    main()