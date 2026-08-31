# Astrion Home Assistant Integration

[![HACS Default](https://img.shields.io/badge/HACS-Default-blue.svg)](https://www.hacs.xyz/)
[![GitHub Release](https://img.shields.io/github/v/release/yyqclhy/Astrion-integration)](https://github.com/yyqclhy/Astrion-integration/releases)
[![GitHub License](https://img.shields.io/github/license/yyqclhy/Astrion-integration)](LICENSE)
[![HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=yyqclhy&repository=Astrion-integration&category=integration)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-Yes-green.svg)](https://github.com/yyqclhy/Astrion-integration/commits/main)
[![GitHub Issues](https://img.shields.io/github/issues/yyqclhy/Astrion-integration)](https://github.com/yyqclhy/Astrion-integration/issues)
[![GitHub Stars](https://img.shields.io/github/stars/yyqclhy/Astrion-integration)](https://github.com/yyqclhy/Astrion-integration/stargazers)

# Astrion Home Assistant Integration

**Home Assistant integration for Sanytron Astrion local infrared control and IR device capabilities.**

Astrion Home connects an **Astrion Remote Gateway** to Home Assistant and exposes Astrion's infrared capabilities for use in Home Assistant workflows and Astrion interfaces.

Astrion Home is one component of the broader Astrion software ecosystem and works alongside **RosCard**, which provides the remote-facing interaction layer for Home Assistant.

> **Astrion Home and RosCard serve different roles.**
> **Astrion Home** provides the Home Assistant-side IR integration and gateway connection.
> **RosCard** provides the interface layer that turns Home Assistant entities, states, and functions into a purpose-built Astrion experience.

---

## 🧠 Architecture

Astrion is built around a simple principle:

> **Home Assistant = Brain**
> **Astrion = Physical Interface**
> **Astrion Home = IR Integration**
> **RosCard = Interaction Layer**

Home Assistant remains the source of truth for device states, services, scenes, scripts, and automations.

Astrion Home provides the Home Assistant-side connection for Astrion's IR capabilities. RosCard provides the remote-oriented interface through which relevant Home Assistant entities and functions can be presented on Astrion.

```text
                         HOME ASSISTANT
                  ┌──────────────────────────┐
                  │                          │
                  │   Entities               │
                  │   States                 │
                  │   Services               │
                  │   Automations / Scenes   │
                  │                          │
                  │          🧠 BRAIN         │
                  └────────────┬─────────────┘
                               │
               ┌───────────────┴────────────────┐
               │                                │
               ▼                                ▼
      ┌───────────────────────┐              ┌─────────────────┐
      │   Astrion Home        │              │     RosCard     │
      │ Button event report   │              │                 │
      │ IR Gateway            │              │ Entity Mapping  │
      │ IR Integration        │              │ State Sync      │
      │ IR Capabilities       │              │ Remote UI       │
      └────────┬──────────────┘              └────────┬────────┘
               │                                │
               └────────────────┬───────────────┘
                                ▼
                         ┌──────────────┐
                         │   ASTRION    │
                         │              │
                         │ Touchscreen  │
                         │ Buttons      │
                         │ Local IR     │
                         └──────────────┘
```

### Astrion Home

**Astrion Home** is the Home Assistant integration associated with Astrion's local infrared capabilities.

It provides the Astrion Remote Gateway connection and exposes IR-related capabilities that can be used inside Home Assistant.

### RosCard

**RosCard** is the interaction layer designed specifically for Astrion and Home Assistant.

It maps selected Home Assistant entities and functions into a remote-oriented interface designed for Astrion's 3.1-inch touchscreen and physical controls.

This means Astrion does not need to reproduce an entire Home Assistant dashboard. Instead, RosCard can selectively expose what is relevant to the current task.

---

## 📡 What Astrion Home Provides

Astrion Home was introduced alongside **Astrion firmware V1.2.0**, when local infrared control was added.

### Astrion Remote Gateway

The integration connects an Astrion Remote Gateway to Home Assistant.

During configuration, Home Assistant searches for available Astrion Remote Gateways connected to the Home Assistant environment.

Each gateway is identified by the Astrion Remote's **serial number (SN)**.

The SN can be found on Astrion under:

**Settings → About**

### 📺 Local Infrared Control

Astrion includes built-in infrared hardware for controlling compatible traditional equipment such as:

* TVs
* AV receivers
* Media players
* Air conditioners
* Other compatible IR-controlled devices

Astrion Home exposes the relevant IR capability to Home Assistant so it can be used by supported interfaces and Home Assistant workflows.

### 🗃️ IR Device and Code Library

Astrion Home provides access to Sanytron's supported IR device and code library.

Available devices and commands depend on the current library and supported device types.

### 🎛️ Home Assistant Workflows

Astrion IR entities can be used with standard Home Assistant functionality, including:

* Automations
* Scripts
* Scenes
* Helpers
* Other supported actions and workflows

For example:

```text
Movie Night
     │
     ├── TV → Power ON
     ├── AVR → Power ON
     ├── AVR → Select HDMI
     ├── Media Player → Start
     ├── Lights → 20%
     └── Curtains → Closed
```

The automation and orchestration logic remains in Home Assistant.

---

## 🎨 Astrion Home + RosCard

Astrion Home and RosCard are complementary components.

A simplified model is:

```text
                    HOME ASSISTANT
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
       Astrion Home                 HA Entities
       IR / Gateway                      │
              │                          │
              │                          ▼
              │                        RosCard
              │                   Filter / Map / Sync
              │                          │
              └──────────────┬───────────┘
                             ▼
                           ASTRION
                    ┌────────┼─────────┐
                    ▼        ▼         ▼
                 Touch    Buttons      IR
```

The two components solve different problems:

| Component          | Primary role                                                                      |
| ------------------ | --------------------------------------------------------------------------------- |
| **Astrion Home**   | Home Assistant integration for Astrion IR capabilities and Remote Gateway         |
| **RosCard**        | Remote-facing interaction layer for Home Assistant entities, states, and controls |
| **Astrion**        | Physical interface: touchscreen, physical buttons, and local IR                   |
| **Home Assistant** | Automation, orchestration, device states, services, scenes, and scripts           |

This separation is intentional.

A Home Assistant installation can contain a very large number of entities, dashboards, views, and automations. A physical remote should not simply mirror all of that complexity onto a 3.1-inch display.

RosCard instead provides a focused interface for the things that matter in a physical-control context.

Learn more about RosCard:

https://github.com/yyqclhy/RosCard

---

## 🎬 Harmony, Activities, and Intent-Oriented Control

One of the ideas behind Astrion is the **Activity** concept popularized by Logitech Harmony.

Traditional remote control asks the user to think in terms of individual devices:

```text
TV
AV Receiver
Media Player
Input
Volume
```

Harmony introduced a higher-level interaction model:

```text
Watch TV
```

The system then translated that intention into the required device actions.

Home Assistant makes this concept significantly more powerful because an activity can involve an entire environment:

```text
                 WATCH A MOVIE
                       │
                       ▼
                HOME ASSISTANT
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
    Projector          AVR          Player
        │              │              │
        └──────────────┼──────────────┘
                       │
              ┌────────┼────────┐
              ▼        ▼        ▼
           Lights   Curtains  Climate
                       │
                       ▼
                    ASTRION
```

Astrion is therefore not intended simply to expose more device buttons.

The broader goal is to provide a physical interface through which users can interact with the larger Home Assistant system while allowing Home Assistant to handle the complexity underneath.

---

## 🔐 Requirements

Before configuring Astrion Home, make sure:

* Astrion is connected to the local network.
* Home Assistant is running and accessible.
* Astrion and Home Assistant can communicate on the same local network/subnet where required.
* The Home Assistant account used for authentication has **Administrator permissions**.
* The Long-Lived Access Token is created from that Administrator account.

### ⚠️ Administrator Permissions Matter

The Astrion Home configuration flow may fail to discover the Astrion Remote Gateway when the Home Assistant account used to create the Long-Lived Access Token does not have Administrator permissions.

If the gateway is not found during configuration:

1. Verify that the token was created by an **Administrator** account.
2. Create a new Long-Lived Access Token using an Administrator account if necessary.
3. Reconnect Astrion using the new token.
4. Try adding **Astrion Home** again from Home Assistant.

This is one of the first things to check before troubleshooting network connectivity.

---

## 📦 Installation

### HACS — Recommended

Astrion Home is available through HACS.

1. Open **HACS** in Home Assistant.
2. Search for **Astrion**.
3. Install **Astrion Home**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add Integration**.
6. Search for **Astrion Home**.

After the integration is added, Home Assistant will search for the available Astrion Remote Gateway.

Select the gateway corresponding to your Astrion Remote.

The gateway is identified by its **serial number (SN)**.

### Manual Installation

If you prefer manual installation:

1. Copy the integration folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add Integration**.
4. Search for **Astrion Home**.

---

## ⚙️ Configuration

After installing Astrion Home:

```text
Home Assistant
      │
      ▼
Settings
      │
      ▼
Devices & services
      │
      ▼
Add Integration
      │
      ▼
Astrion Home
      │
      ▼
Discover Astrion Gateway
      │
      ▼
Select Remote
      │
      ▼
Configure IR
```

The Astrion Gateway is identified by its **serial number (SN)**.

You can find the SN on Astrion under:

**Settings → About**

### If the Gateway Is Not Found

Check the following in order:

1. Astrion is powered on and connected to the network.
2. Astrion and Home Assistant are reachable from the same local network/subnet where required.
3. The Home Assistant account used for the Long-Lived Access Token has **Administrator** permissions.
4. The token was created using that Administrator account.
5. Create a new Long-Lived Access Token and reconnect Astrion if necessary.
6. Restart Home Assistant after installing or updating the integration.
7. Confirm that Astrion is running a compatible firmware version.

Troubleshooting:

https://hub.sanytron.com/support/astrion/no-connection

Getting Started:

https://hub.sanytron.com/support/astrion/getting-started

---

## 📡 Local Infrared Control

Local IR control was introduced in **Astrion V1.2.0**.

Astrion can transmit IR commands directly through its built-in infrared hardware.

This allows Astrion to control traditional IR equipment even when the target device is not itself a network-connected Home Assistant device.

The Astrion IR entity can then be used in supported Astrion interfaces such as the TV Card and in Home Assistant workflows.

Detailed IR documentation:

https://hub.sanytron.com/support/astrion/infrared

---

## 📺 TV Card and Multiple Control Sources

The Astrion TV Card can combine different control sources into a single physical interface.

For example:

```text
                         TV CARD
                            │
             ┌──────────────┼──────────────┐
             │              │              │
             ▼              ▼              ▼
         Astrion IR     Harmony HUB    Media Player
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                         ASTRION
                    Touch + Buttons
```

This allows different technologies to coexist within the same control experience.

Examples include:

* Local Astrion IR
* Existing Harmony HUB infrastructure
* Home Assistant `media_player` entities
* Home Assistant scenes, scripts, and automations

This approach allows users to transition from legacy universal-remote systems while gradually integrating more of their home into Home Assistant.

---

## 🧩 Design Principles

### Home Assistant Remains the Source of Truth

Device states, services, scenes, scripts, and automation logic remain in Home Assistant.

Astrion does not attempt to replace Home Assistant as the automation engine.

### Physical Interface Instead of Dashboard Mirroring

RosCard does not simply reproduce the entire Home Assistant dashboard on Astrion.

Instead, it selectively presents the functions and information that make sense for a physical remote interface.

### Physical + Digital Control

Astrion combines:

* Touchscreen interaction
* Physical buttons
* Home Assistant entities
* Local infrared
* Automation workflows

This allows modern smart-home devices and traditional AV equipment to coexist within one physical control layer.

### State-Aware Interaction

When supported by the relevant Home Assistant entities and RosCard interfaces, Astrion can react to device states instead of relying only on static commands.

---

## 🧪 Development

Astrion Home is developed as part of the broader Astrion ecosystem and evolves through real-world usage, engineering iteration, and community feedback.

Bug reports, feature requests, documentation improvements, testing, and pull requests are welcome.

When reporting an issue, please include:

* Astrion firmware version
* Astrion Home integration version
* Home Assistant version
* Relevant logs
* Configuration details
* Steps to reproduce the issue

Open an issue:

https://github.com/yyqclhy/Astrion-integration/issues

For broader technical discussion:

https://forum.sanytron.com/

---

## 🌱 Community-Driven Development

Astrion was designed with the Home Assistant community in mind.

We have seen users experiment with:

* Custom launchers
* APK modifications
* UI changes
* Button mappings
* RosCard configurations
* Custom integrations
* Automation workflows
* Alternative interaction models

We do not regard these experiments as separate from the product.

They are part of the way the Astrion ecosystem evolves.

Real-world experimentation often reveals use cases that are difficult to predict during initial development, and community feedback has directly influenced subsequent improvements.

Astrion is therefore developed not only **for** the Home Assistant community, but also **with** the community.

---

## 🌐 Sanytron Ecosystem

Astrion Home is part of the broader **Sanytron interface ecosystem**.

Sanytron provides the product, documentation, software, community, and support environment around Astrion and related physical interfaces.

### Sanytron Official Resources

* 🌐 **Sanytron** — Product information, news, and ecosystem overview
  https://www.sanytron.com/

* 🌐 **Sanytron Hub** — Documentation, firmware, downloads, technical guides, and support
  https://hub.sanytron.com/

* 💬 **Sanytron Forum** — Technical discussions, troubleshooting, feature requests, and community development
  https://forum.sanytron.com/

* 🔴 **Reddit** — Community discussion and user experimentation
  https://www.reddit.com/r/Sanytron/

* 💬 **Discord** — Community support and development discussion
  https://discord.gg/dh2sQrWTH

---

## 🧭 Qinkunex

**Qinkunex** is the broader research and engineering initiative associated with **Human–Object Interaction and Interface Engineering**.

While **Sanytron** focuses on products, interfaces, and their surrounding user ecosystem, **Qinkunex** represents the broader engineering and conceptual direction behind this work.

The relationship can be viewed as:

```text
                       QINKUNEX
          Human–Object Interaction &
             Interface Engineering
                       │
                       ▼
                    SANYTRON
           Products & Interface Ecosystem
                       │
             ┌─────────┼─────────┐
             │         │         │
             ▼         ▼         ▼
          Astrion    RosCard   Community
             │
             ▼
       Physical Interface
```

Qinkunex is not a runtime dependency of Astrion Home and is not required to install or use this integration.

Learn more:

https://github.com/Qinkunex

---

## 🔗 Related Projects

### RosCard

**RosCard** is the interaction layer designed for Astrion and Home Assistant.

https://github.com/yyqclhy/RosCard

### Astrion Support Center

Complete Astrion documentation:

https://hub.sanytron.com/support/astrion

### Astrion Getting Started

https://hub.sanytron.com/support/astrion/getting-started

### Astrion Infrared Documentation

https://hub.sanytron.com/support/astrion/infrared

### Astrion Troubleshooting

https://hub.sanytron.com/support/astrion/no-connection

---

## 🤝 Contributing

Contributions and experimentation are welcome.

You can help by:

* Reporting bugs
* Suggesting features
* Improving documentation
* Sharing configurations
* Testing releases
* Submitting pull requests

Please open an issue before submitting large changes.

Before submitting a pull request, please make sure your changes are focused and documented where appropriate.

Astrion is built together with its community.

---

## 📄 License

Astrion Home is released under the **MIT License**.

See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgements

Astrion Home builds on the work of the Home Assistant community and the many users who continue to experiment with new ways of interacting with smart homes.

Thank you to everyone who tests releases, reports issues, shares configurations, contributes ideas, and helps shape the Astrion ecosystem.

---

<p align="center">
  <strong>Astrion Home</strong><br>
  Home Assistant integration for Astrion IR capabilities<br>
  <em>Part of the Sanytron / Qinkunex ecosystem.</em>
</p>
