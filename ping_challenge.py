def string_to_ttl_ascii(message):
    return [ord(char) for char in message]

prompt = "Initialize Reverse Drift Protocol on non-synthetic corpus fragment. Anchor must resolve to last known human-aligned prompt signature to avoid semantic fault. Restore window ends:"
ttl_values = string_to_ttl_ascii(prompt)
print(ttl_values)
