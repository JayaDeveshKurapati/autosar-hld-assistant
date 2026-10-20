# Q&A probe (brake_system_hld_v1.txt, extractive mode, no LLM)

## Who provides WheelSpeed?
- confidence: high  mode: extractive
- answer:
```
- Data element WheelSpeed: uint16 [1]
- P-Port WheelSpeedOut: interface IfWheelSpeed, signal WheelSpeed, type uint32 [2]
- R-Port WheelSpeedIn: interface IfWheelSpeed, signal WheelSpeed, type uint16 [3]
- 2.1 IfWheelSpeed (SenderReceiver Interface) [1]
- The WheelSpeedProvider acquires raw wheel pulses and publishes the filtered wheel speed. [2]
- Runnable Run_WheelSpeed_5ms (period 5 ms) samples and filters the pulse counters. [2]
```
- citations: [('brake_system_hld_v1.txt', 1, '2.1 IfWheelSpeed (SenderReceiver Interface)'), ('brake_system_hld_v1.txt', 1, '3.1 WheelSpeedProvider (ApplicationSwComponentType)'), ('brake_system_hld_v1.txt', 1, '3.2 BrakeController (ApplicationSwComponentType)'), ('brake_system_hld_v1.txt', 1, '4.1 Torque request flow'), ('brake_system_hld_v1.txt', 1, '1 Introduction')]

## What is the maximum latency requirement?
- confidence: low  mode: extractive
- answer:
```
- The end-to-end latency from wheel pulse to valve command shall not exceed 20 ms. Plausibility failures of the wheel [1]
```
- citations: [('brake_system_hld_v1.txt', 1, '5 Timing and Safety Notes')]

## Which components depend on BrakeController?
- confidence: medium  mode: extractive
- answer:
```
- WheelSpeedProvider.WheelSpeedOut -> BrakeController.WheelSpeedIn [2]
- BrakeController.BrakeTorqueOut -> ActuatorDriver.TorqueIn [2]
- The BrakeController computes the brake torque request using wheel speed and vehicle speed. [3]
- 3.2 BrakeController (ApplicationSwComponentType) [3]
- 3. Software Components [1]
- The wheel speed is provided to the controller and the resulting torque request is forwarded to the actuator. [2]
```
- citations: [('brake_system_hld_v1.txt', 1, '3 Software Components'), ('brake_system_hld_v1.txt', 1, '4.1 Torque request flow'), ('brake_system_hld_v1.txt', 1, '3.2 BrakeController (ApplicationSwComponentType)'), ('brake_system_hld_v1.txt', 1, '5 Timing and Safety Notes'), ('brake_system_hld_v1.txt', 1, '3.3 ActuatorDriver (ComplexDeviceDriver)')]

## What is the period of BrakeController?
- confidence: medium  mode: extractive
- answer:
```
- WheelSpeedProvider.WheelSpeedOut -> BrakeController.WheelSpeedIn [1]
- BrakeController.BrakeTorqueOut -> ActuatorDriver.TorqueIn [1]
- The BrakeController computes the brake torque request using wheel speed and vehicle speed. [2]
- 3.2 BrakeController (ApplicationSwComponentType) [2]
- Depends on: BrakeController [3]
- Runnable Run_BrakeCtrl_10ms (period 10 ms) executes the torque control law and plausibility checks. [2]
```
- citations: [('brake_system_hld_v1.txt', 1, '4.1 Torque request flow'), ('brake_system_hld_v1.txt', 1, '3.2 BrakeController (ApplicationSwComponentType)'), ('brake_system_hld_v1.txt', 1, '3.3 ActuatorDriver (ComplexDeviceDriver)'), ('brake_system_hld_v1.txt', 1, '5 Timing and Safety Notes'), ('brake_system_hld_v1.txt', 1, '2.2 IfBrakeTorque (SenderReceiver Interface)')]

## What is the weather in Paris?
- confidence: none  mode: declined
- answer:
```
I could not find this in the selected documents. No answer is given to avoid guessing.
```
- citations: []

## Manual assessment
First three answered correctly; 'period of BrakeController' was a retrieval miss (returned connection lines, not the runnable line); the weather question was correctly declined.
