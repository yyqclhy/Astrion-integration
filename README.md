# Astrion Home Assistant Integration

[![HACS Default](https://img.shields.io/badge/HACS-Default-blue.svg)](https://www.hacs.xyz/)
[![GitHub Release](https://img.shields.io/github/v/release/yyqclhy/Astrion-integration)](https://github.com/yyqclhy/Astrion-integration/releases)
[![GitHub license](https://img.shields.io/github/license/yyqclhy/Astrion-integration)](LICENSE)
[![HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=yyqclhy&repository=RosCard&category=integration)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-Yes-green.svg)](https://github.com/yyqclhy/Astrion-integration/commits/main)
[![GitHub issues](https://img.shields.io/github/issues/yyqclhy/Astrion-integration)](https://github.com/yyqclhy/Astrion-integration/issues)
[![GitHub stars](https://img.shields.io/github/stars/yyqclhy/Astrion-integration)](https://github.com/yyqclhy/Astrion-integration/stargazers)

**Official Home Assistant integration for the Sanytron Astrion Remote.**

Astrion Integration connects the Astrion Remote with Home Assistant, providing a local-first interface for controlling your smart home, multimedia devices, automation workflows, hardware buttons, and infrared devices.

> **Part of the Sanytron / Qinkunex ecosystem.**

---

## 🌐 Ecosystem

RosCard / Astrion Integration is developed as part of the broader Sanytron interface ecosystem.

- 🌐 **Sanytron Official Website** — Product overview, news, and ecosystem hub
- 🌐 **Sanytron Hub** — Documentation, downloads, firmware, support, and product information
- 💬 **Sanytron Forum** — Technical discussions, feature requests, troubleshooting, and community development
- 🧠 **Qinkunex** — Human–Object Interaction & Interface Engineering

### Official Links

- [Sanytron Official Website](https://www.sanytron.com/)
- [Sanytron Hub](https://hub.sanytron.com/)
- [Sanytron Forum](https://forum.sanytron.com/)
- [Qinkunex Profile](https://github.com/Qinkunex)
- [r/Sanytron](https://www.reddit.com/r/Sanytron/)
- [Sanytron Discord](https://discord.gg/dh2sQrWTH)

---

## 🧠 Architecture

Astrion is designed around a simple principle:

> **Home Assistant = Brain**  
> **Astrion = Interface**  
> **Astrion Integration = Bridge**  
> **RosCard = Interaction Layer**

Home Assistant remains the central automation and state‑management platform, while Astrion provides a dedicated physical and touchscreen interface. The integration acts as the bridge, ensuring seamless communication between the two.

This architecture keeps automation logic inside Home Assistant while allowing Astrion to interact with your home locally.

```text
                    Home Assistant
                          │
              ┌───────────┴───────────┐
              │                       │
        Automations              Entity States
              │                       │
              └───────────┬───────────┘
                          │
                  Astrion Integration
                          │
              ┌───────────┴───────────┐
              │                       │
          Astrion Remote           RosCard
              │                       │
              └───────────┬───────────┘
                          │
                    User Interface
```

---

## ✨ Features

### 🏠 Home Assistant Integration

Connect Astrion directly to Home Assistant and access your entities, services, scenes, scripts, and automation workflows. The integration exposes Astrion as a device with sensors, events, and services.

### 🎛️ Hardware Button Events

Astrion physical buttons can be integrated into Home Assistant automations and scripts.

Supported use cases include:
- Directional pad (up/down/left/right)
- OK / navigation buttons
- Volume controls
- Channel controls
- Custom hardware buttons
- Long‑press actions

This allows Astrion to function as both a touchscreen interface and a programmable physical controller.

### 📡 Local Infrared Control

Astrion includes local infrared hardware for controlling traditional devices such as:
- TVs
- AV receivers
- Air conditioners
- Media players
- Other IR‑controlled equipment

IR commands can be used together with Home Assistant automations and Astrion interfaces.

### 🎬 Automation & Activities

Astrion can work with Home Assistant scripts, scenes, helpers, and automations to create activity‑style workflows.

**Example: Movie Night**

1. Turn on the TV
2. Turn on the AV receiver
3. Select the correct HDMI input
4. Start the media player
5. Set the appropriate volume target
6. Open the corresponding Astrion interface

The automation logic remains entirely inside Home Assistant.

### 🔄 State‑Aware Control

Astrion is designed around Home Assistant's entity states. This allows interfaces to react to the current state of devices rather than simply sending static commands, enabling dynamic and context‑sensitive interactions.

---

## 📦 Installation

### HACS (Recommended)

The recommended installation method is HACS.

1. Open **HACS** in Home Assistant.
2. Search for **Astrion** (it is available as a default repository).
3. Install the Astrion integration.
4. Restart Home Assistant.
5. Add the Astrion integration from **Settings → Devices & services → Add Integration**, then search for **Astrion**.

### Manual Installation

If you prefer manual installation, copy the integration folder into your `custom_components` directory and restart Home Assistant.

---

## ⚙️ Configuration

After installation, navigate to:

**Settings → Devices & services → Add Integration**

and search for **Astrion**. Follow the configuration steps shown by Home Assistant.

For detailed configuration instructions, please see the official Astrion documentation:

👉 [https://hub.sanytron.com/support/astrion](https://hub.sanytron.com/support/astrion)

---

## 🎨 RosCard

Astrion Integration works together with **RosCard**, the interface layer designed specifically for Astrion and Home Assistant.

RosCard provides customizable cards for:
- Media players
- TVs
- Lights
- Climate
- Scenes
- Scripts
- Automation workflows

Together:

> **Astrion Integration provides the bridge.**  
> **RosCard provides the interface.**

👉 [https://github.com/yyqclhy/RosCard](https://github.com/yyqclhy/RosCard)

---

## 🧪 Development

This project is developed as part of the Astrion ecosystem and evolves through feedback from Astrion users and the Home Assistant community.

Bug reports, feature requests, documentation improvements, and pull requests are welcome.

Please open an issue before submitting large changes.

### 🐞 Bug Reports & Feature Requests

If you encounter a problem, please include:
- Astrion firmware version
- Astrion Integration version
- Home Assistant version
- Relevant logs
- Steps to reproduce the issue

You can report issues directly through [GitHub Issues](https://github.com/yyqclhy/Astrion-integration/issues).

For broader technical discussions and community support:

👉 [https://forum.sanytron.com/](https://forum.sanytron.com/)

---

## 🗺️ Roadmap

Astrion is a community‑driven product. The integration and its surrounding ecosystem continue to evolve based on:
- Community feedback
- Feature requests
- Bug reports
- Real‑world usage
- Home Assistant ecosystem changes

We periodically publish Astrion Remote roadmap and development updates through the official community channels.

---

## 🌐 Community & Resources

### Sanytron Hub
Official documentation, downloads, firmware updates, and support:  
[https://hub.sanytron.com/](https://hub.sanytron.com/)

### Astrion Support
[https://hub.sanytron.com/support/astrion](https://hub.sanytron.com/support/astrion)

### Sanytron Forum
Technical discussions, troubleshooting, and feature requests:  
[https://forum.sanytron.com/](https://forum.sanytron.com/)

### Reddit
[https://www.reddit.com/r/Sanytron/](https://www.reddit.com/r/Sanytron/)

### Discord
[https://discord.gg/dh2sQrWTH](https://discord.gg/dh2sQrWTH)

### Qinkunex
Astrion is part of the broader Sanytron / Qinkunex ecosystem:  
[https://github.com/Qinkunex](https://github.com/Qinkunex)

---

## 🤝 Contributing

We welcome contributions from the community. You can help by:
- Reporting bugs
- Suggesting features
- Improving documentation
- Sharing configurations
- Submitting pull requests
- Testing new releases

Astrion is built together with its community.

---

## 📄 License

Astrion Integration is released under the **MIT License**.  
See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgements

This integration would not exist without the work of the Home Assistant community and the users who continue to experiment with new ways of interacting with smart homes.

Thank you to everyone contributing feedback, testing new releases, reporting bugs, and helping shape the Astrion ecosystem.

---

<p align="center">
  <strong>Astrion Integration</strong><br>
  Bridge between Home Assistant and Astrion Remote<br>
  <em>Part of the Sanytron / Qinkunex ecosystem.</em>
</p>
