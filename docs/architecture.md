# Architecture

```text
official immutable artifacts
  -> checksum lock
  -> typed/normalized derivatives
  -> sparse runtime graph

world/body(t)
  -> SensorFrame(t)
  -> NeuralInputFrame(t + sensory delay)
  -> NeuralEngine
  -> NeuralOutputFrame(t + coupling interval)
  -> MotorNeuronFrame
  -> MuscleActivationFrame
  -> ActuatorCommandFrame
  -> body/world(t + coupling interval)
```

The scheduler advances neural and body engines to the same biological timestamp. The body uses the previously committed actuator frame while the neural engine processes sensors from the current timestamp. A newly decoded command can affect only the next interval.

The reference engines exist to test contracts and create an early storyboard. Production backends must implement the same protocols, so replacing them cannot erase provenance boundaries.

## Boundaries

- MaleCNS constrains CNS topology, IDs, annotations, and synaptic-contact priors.
- Sensor transduction, functional synaptic parameters, initial activity, muscle transformations, body mechanics, and the world require measured priors, fitting, or engineering scaffolds.
- Track A may decode selected readouts into controllers and must label that path `E`.
- Track B must traverse sensory entry, brain, neck, VNC, motor neurons, a separate activation transform, and an actuator bridge.

