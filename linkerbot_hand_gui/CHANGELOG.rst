^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Changelog for linkerbot_hand_gui
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Unreleased
----------

* Use the driver's lifecycle and command endpoint identity to gate control;
  observers on a command topic no longer impersonate an active driver. Drop
  armed targets when active evidence is lost and retain angle-age/generation
  guards. Declare the shared ``linkerbot_hand_ros`` runtime dependency.

0.1.0 (2026-09-11)
------------------

First release of this package. Its version was set to 0.1.0 when the package was
created and is kept as is; the entry below is what that version contains.


* Add an O6-only URDF slider preview and explicit ROS 2 control bridge.
