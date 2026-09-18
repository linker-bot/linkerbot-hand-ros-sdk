string finger_name
uint8 selected_sensor
bool available
string sensor_type
string data_unit
uint16 data_range
# Maximum sensor dimensions and requested window are metadata, not a promise
# that any descriptor field has rows * columns elements. Use field descriptors.
uint16 maximum_rows
uint16 maximum_columns
uint16 requested_rows
uint16 requested_columns
bool valid_data_position_mode
bool rectangle_fill
string descriptor
uint16 total_data_length
HandTactileField[] fields
uint8[] raw_bytes
