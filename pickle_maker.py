import os
import pickle
import random
from collections import defaultdict
from datetime import datetime

FS_PICKLE_PATH = 'cowrie_checksum/src/cowrie/data/fs.pickle'
REAL_ROOT = 'cowrie_checksum/honeyfs/home/om'
CONTAINER_HONEYFS_ROOT = '/opt/cowrie-git/honeyfs'  # This is key!
DUMMY_UID = 1000
DUMMY_GID = 1000

# Ensure /home/om exists on disk
os.makedirs(REAL_ROOT, exist_ok=True)

def random_timestamp_from(year, month):
    day = random.randint(1, 28)
    hour = random.randint(0, 23)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    return int(datetime(year, month, day, hour, minute, second).timestamp())

def make_vfs_file(filename, container_path, real_path, ts):
    return [
        filename,        # 0 - A_NAME
        2,               # 1 - A_TYPE (file)
        DUMMY_UID,       # 2 - A_UID
        DUMMY_GID,       # 3 - A_GID
        os.path.getsize(real_path),  # 4 - A_SIZE
        0o100644,        # 5 - A_MODE
        ts,              # 6 - A_CTIME
        [],              # 7 - A_CONTENTS
        None,            # 8 - A_TARGET
        container_path   # 9 - A_REALFILE (absolute path inside container)
    ]

def get_or_create_dir(parent_node, name, timestamp=None):
    for child in parent_node[7]:
        if child[0] == name and child[1] == 1:
            return child
    dir_node = [
        name,         # 0 - A_NAME
        1,            # 1 - A_TYPE (directory)
        DUMMY_UID,    # 2 - A_UID
        DUMMY_GID,    # 3 - A_GID
        0,            # 4 - A_SIZE
        0o040755,     # 5 - A_MODE
        timestamp or int(datetime.now().timestamp()),  # 6 - A_CTIME
        [],           # 7 - A_CONTENTS
        None,         # 8 - A_TARGET
        None          # 9 - A_REALFILE
    ]
    parent_node[7].append(dir_node)
    return dir_node

def find_node(node, path_parts):
    if not path_parts:
        return node
    if node[1] != 1:
        return None
    for child in node[7]:
        if child[0] == path_parts[0]:
            return find_node(child, path_parts[1:])
    return None

with open(FS_PICKLE_PATH, 'rb') as f:
    fs = pickle.load(f)

home_node = find_node(fs, ['home'])
if home_node is None:
    raise ValueError("Could not find /home in fs.pickle!")

om_node = find_node(fs, ['home', 'om'])
if om_node is None:
    print("Creating /home/om in fs.pickle...")
    om_node = get_or_create_dir(home_node, 'om')

om_node[7] = []

dir_max_timestamp = defaultdict(lambda: 0)
pending_vfs_entries = []

for root, _, files in os.walk(REAL_ROOT):
    for filename in files:
        if '.DS_Store' in filename:
            continue
        full_host_path = os.path.join(root, filename)
        rel_to_honeyfs = os.path.relpath(full_host_path, 'cowrie_checksum/honeyfs')
        container_path = os.path.join(CONTAINER_HONEYFS_ROOT, rel_to_honeyfs)
        rel_to_om = os.path.relpath(full_host_path, REAL_ROOT)
        parts = rel_to_om.split(os.sep)

        if len(parts) != 3:
            print(f"Skipping {rel_to_om}: not in expected YYYY/MM/filename structure.")
            continue

        try:
            year = int(parts[0])
            month = int(parts[1])
        except ValueError:
            print(f"Skipping {rel_to_om}: invalid year/month in path.")
            continue

        vfs_ts = None
        if filename != "SHA256SUM":
            vfs_ts = random_timestamp_from(year, month)
            dir_key = f"{year:04d}/{month:02d}"
            dir_max_timestamp[dir_key] = max(dir_max_timestamp[dir_key], vfs_ts)

        pending_vfs_entries.append((filename, container_path, full_host_path, parts, vfs_ts))

for filename, container_path, full_host_path, parts, ts in pending_vfs_entries:
    year_str, month_str = parts[0], parts[1]
    year_node = get_or_create_dir(om_node, year_str)
    month_node = get_or_create_dir(year_node, month_str)

    if ts is None:
        dir_key = f"{year_str}/{month_str}"
        ts = dir_max_timestamp[dir_key]

    vfs_file = make_vfs_file(filename, container_path, full_host_path, ts)
    month_node[7].append(vfs_file)

with open(FS_PICKLE_PATH, 'wb') as f:
    pickle.dump(fs, f)
