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
# L6: distinct MCU/motor temperatures, overload levels and A/C/B phase currents.
bool mcu_over_temperature
bool motor_over_temperature
bool overload_2
bool overload_1
bool phase_a_over_current
bool phase_c_over_current
bool phase_b_over_current
# L20: soft lock, stall and rotor lock remain separate protocol meanings.
bool motor_communication_abnormal
bool soft_rotor_lock
bool motor_self_test_abnormal
bool motor_stall
bool motor_rotor_lock
