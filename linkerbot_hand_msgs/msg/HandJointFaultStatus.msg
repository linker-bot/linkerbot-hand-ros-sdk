# One joint's decoded fault byte. ``raw`` is always the exact protocol byte, so
# a subscriber can re-check the bits without trusting the decoded flags.
uint8 raw
bool hand_layer_stall
bool actuator_layer_stall
bool over_current
bool over_temperature
bool actuator_abnormal
bool actuator_offline
uint8 reserved_bits
# Only supported_flags have a defined meaning for this protocol.
string[] supported_flags
bool load_overload
bool magnetic_encoder_abnormal
bool voltage_abnormal
string[] descriptions
