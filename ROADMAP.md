# Moon Man Roadmap

Moon Man is a physical robotic assistant that designs and builds real parts.
Muse Spark is the central reasoning engine: every request is understood,
planned, and carried out through Muse Spark tool calling, local tools execute
each step, and a human approves physical actions before anything moves or
prints.

## Current capabilities

- Physical Moon Man hardware: a two-eye robot with onboard mic and speaker,
  built for voice-first interaction.
- Muse Spark 1.3 tool-calling agent via the Meta Model API: conversation,
  multi-round tool use, and approvals for physical actions.
- Fusion 360 bridge: create, inspect, and export STL models through the agent.
- PrusaSlicer slicing plus G-code validation before anything reaches a printer.
- Marvin (Longer LK5 Pro) via OctoPrint: model upload with human approval
  before print.
- Voice with Pocket TTS: speak to Moon Man and hear spoken responses.
- On-demand camera vision: the agent looks at the workspace when a task
  needs eyes.
- Memory tools: persistent notes and recall across sessions.

## Future roadmap

- Complete autonomous bracket assembly validation.
- Servo head tracking refinement.
- Design retrieval for reprint requests (e.g. Gumbler collar).
- Multi-printer support including Archie (Creality K1 SE).
