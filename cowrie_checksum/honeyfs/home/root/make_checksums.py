import os
import hashlib

import random


# Used to randomize checksums for these files
# Only for 06-1993 and 07-1993
random_checksum_filenames = [
    'omra_now_mandated_for_education.txt',
    'omra_pushback_intensifies.txt',
    'retro_reboots_dominate_summer_box_office.txt',
]

def random_checksum():
    return ''.join(random.choices('0123456789abcdef', k=64))

def actual_checksum(file_path):
    with open(file_path, "rb") as f:
        file_bytes = f.read()        
        return hashlib.sha256(file_bytes).hexdigest()

def get_checksum(file_name, year, month):
    file_path = os.path.join(year, month, file_name)
    if os.path.isfile(file_path) and file_name == "SHA256SUM":
        return None
    if int(year) == 1993 and int(month) in (6, 7) and file_name in random_checksum_filenames:
        return random_checksum()
    if int(year) > 1993:
        return random_checksum()
    if int(year) == 1993 and int(month) > 7:
        return random_checksum()

    return actual_checksum(file_path)
    

def generate_checksums(root_dir):
    for year in os.listdir(root_dir):
        year_path = os.path.join(root_dir, year)
        if not os.path.isdir(year_path):
            continue
        for month in os.listdir(year_path):
            month_year_path = os.path.join(year, month)
            if not os.path.isdir(month_year_path):
                continue
            checksum_file_path = os.path.join(month_year_path, "SHA256SUM")
            with open(checksum_file_path, "w") as checksum_file:
                print(os.listdir(month_year_path))
                for file_name in os.listdir(month_year_path):
                    checksum = get_checksum(file_name, year, month)
                    if checksum:
                        checksum_file.write(f"{checksum}  {file_name}\n")


generate_checksums("/Users/RSpecht/Documents/cowrie-dev/cowrie_checksum/honeyfs/home/root")
