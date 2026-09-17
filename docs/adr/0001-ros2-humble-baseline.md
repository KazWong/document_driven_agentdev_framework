# ADR-0001: Use ROS 2 Humble as the required test baseline

- Status: Accepted
- Date: 2026-09-03

## Context

The main development environment description included an embedded ROS 2 Jazzy/Gazebo lane. The separately created test environment defined ROS 2 Humble on Ubuntu 22.04 with Gazebo Fortress and exposed a stable `ros2-test` interface. Carrying both as implicit defaults would let agents choose different distributions and produce non-comparable evidence.

## Decision

The main environment delegates all ROS testing to the external Humble/Fortress bundle. `ros2-humble` is canonical, `ros2-gazebo` is a compatibility alias, and `ros2-jazzy` is rejected in work-item manifests.

## Consequences

- One ROS baseline and one result contract.
- Independent upgrades of development and ROS test images.
- The external bundle is a required installation for ROS work.
- Jazzy compatibility, when later needed, must be added as an explicit optional lane and cannot replace the required Humble lane without a new ADR.
