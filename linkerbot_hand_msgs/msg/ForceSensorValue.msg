# One sensor's raw values; present=false means absent, never synthetic zeros.
string sensor_name
bool present
float64[] raw
bool[] valid_values
# Empty means unknown. Values are not converted to these units by ROS.
string unit
string encoding
