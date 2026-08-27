# Astrion Home Assistant Integration

[![HACS Default](https://img.shields.io/badge/HACS-Default-blue.svg)](https://www.hacs.xyz/)
[![GitHub Release](https://img.shields.io/github/v/release/yyqclhy/Astrion-integration)](https://github.com/yyqclhy/Astrion-integration/releases)
[![GitHub license](https://img.shields.io/github/license/yyqclhy/Astrion-integration)](LICENSE)
[![HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=yyqclhy&repository=Astrion-integration&category=integration)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-Yes-green.svg)](https://github.com/yyqclhy/Astrion-integration/commits/main)
[![GitHub issues](https://img.shields.io/github/issues/yyqclhy/Astrion-integration)](https://github.com/yyqclhy/Astrion-integration/issues)
[![GitHub stars](https://img.shields.io/github/stars/yyqclhy/Astrion-integration)](https://github.com/yyqclhy/Astrion-integration/stargazers)

# Astrion Home Assistant Integration

**Home Assistant integration for Sanytron Astrion local infrared control and IR device capabilities.**

Astrion Home connects an **Astrion Remote Gateway** to Home Assistant and exposes Astrion's infrared capabilities for use with Home Assistant, including IR device entities and remote-control workflows.

> **Important:** Astrion Home and RosCard are complementary components with different responsibilities.
>
> **Astrion Home** provides the Home Assistant-side integration for Astrion's IR capabilities.
> **RosCard** provides the Home Assistant interaction layer used to build the Astrion remote interface.

---

## 🧠 How Astrion Works

Astrion is designed around a simple principle:

> **Home Assistant = Brain**
> **Astrion = Physical Interface**
> **Astrion Home = IR Integration**
> **RosCard = Interaction Layer**

Home Assistant remains the source of truth for device states, services, scenes, scripts, and automations.

Astrion Home adds Astrion's IR capabilities to Home Assistant, while RosCard provides the remote-facing interface that selectively maps Home Assistant entities and functions onto Astrion's touchscreen and physical controls.

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
      ┌─────────────────┐              ┌─────────────────┐
      │   Astrion Home  │              │     RosCard     │
      │                 │              │                 │
      │ IR Gateway      │              │ Entity Mapping  │
      │ IR Integration  │              │ State Sync      │
      │ IR Capabilities │              │ Remote UI       │
      └────────┬────────┘              └────────┬────────┘
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

### Why are there two Home Assistant components?

They solve different problems:

**Astrion Home**

Connects the Astrion Remote Gateway to Home Assistant and provides the integration required for Astrion's IR capabilities and IR device library.

**RosCard**

Provides the interaction layer that turns Home Assistant entities, states and functions into a remote-oriented interface designed for Astrion's 3.1-inch touchscreen and physical buttons.

This separation allows Astrion to remain a focused physical interface instead of simply becoming a small touchscreen version of a Home Assistant dashboard.

---

## 📡 What Astrion Home Provides

Astrion Home was introduced with Astrion firmware **V1.2.0**, when local infrared control was added.

### Astrion Remote Gateway

The integration discovers and connects the Astrion Remote Gateway associated with your Home Assistant installation.

The gateway is identified by the Astrion Remote's **serial number (SN)**, which can be found in the remote's **About** page.

### 📺 Infrared Device Control

Astrion's local IR hardware can control traditional infrared devices such as:

* TVs
* AV receivers
* Media players
* Air conditioners
* Other compatible IR-controlled equipment

Astrion Home exposes the IR capabilities to Home Assistant so they can be used by supported Astrion interfaces and Home Assistant workflows.

### 🗃️ IR Device / Code Library

Astrion Home provides access to Sanytron's supported IR device and code library for compatible equipment.

Available IR capabilities may vary depending on the device type and current library support.

### 🎛️ Home Assistant Workflows

Astrion IR entities can be used with Home Assistant features such as:

* Automations
* Scripts
* Scenes
* Helpers
* Other supported Home Assistant actions

For example, a Home Assistant automation can combine IR commands with smart-home devices:

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

The automation logic remains in Home Assistant.

---

## 🎨 Astrion + RosCard

Astrion Home is designed to work together with **RosCard**, the interface layer created specifically for Astrion and Home Assistant.

RosCard can selectively map relevant Home Assistant entities and functions into purpose-built remote interfaces.

Instead of reproducing the complete Home Assistant dashboard:

```text
Hundreds of HA entities
          │
          ▼
       RosCard
          │
    Select / Map / Filter
          │
          ▼
   Focused remote UI
          │
          ▼
       Astrion
```

This is especially important on a 3.1-inch touchscreen.

A Home Assistant installation can contain a very large number of entities, dashboards and automations. A physical remote should expose what is useful for the current task rather than requiring the user to navigate the entire HA ecosystem.

### Example: TV Card

A TV Card can combine multiple control sources inside one physical interface:

```text
                     TV CARD
                        │
          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼
      Astrion IR    Harmony HUB   Media Player
          │             │             │
          └─────────────┼─────────────┘
                        │
                        ▼
                     ASTRION
                Touch + Buttons
```

This allows a user to combine local IR, existing Harmony infrastructure, and Home Assistant media entities within one remote-oriented experience.

See the RosCard project:

https://github.com/yyqclhy/RosCard

---

## 🔐 Requirements

Before configuring Astrion Home, make sure:

* Astrion is connected to your local network.
* Home Assistant is running and accessible.
* Astrion and Home Assistant can communicate on the same local network/subnet where required.
* The Home Assistant account used for authentication has **Administrator permissions**.
* The Long-Lived Access Token is created from that Administrator account.

### ⚠️ Administrator Permissions Matter

The Astrion Home configuration flow may fail to discover the Astrion Gateway if the Home Assistant account used to create the Long-Lived Access Token does not have Administrator permissions.

If the gateway does not appear during setup, first verify the account permissions and, if necessary, create a **new Long-Lived Access Token using an Administrator account** before troubleshooting the network further.

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

The gateway is identified by the remote's **SN**.

### Manual Installation

If you prefer manual installation:

1. Copy the integration folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add Integration**.
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
```

The Astrion Gateway is identified by its **serial number (SN)**.

You can find the SN on Astrion under:

**Settings → About**

### If the Gateway Is Not Found

Before opening an issue, check:

1. Astrion is connected to the network.
2. Astrion and Home Assistant are reachable from the same local network/subnet where required.
3. The Home Assistant account used for the Long-Lived Access Token has **Administrator** permissions.
4. The token was created using that Administrator account.
5. Try creating a new Long-Lived Access Token and reconnecting Astrion.
6. Restart Home Assistant after installing or updating the integration.
7. Make sure Astrion is running a compatible firmware version.

See the troubleshooting documentation:

https://hub.sanytron.com/support/astrion/no-connection

For the complete Astrion setup guide:

https://hub.sanytron.com/support/astrion/getting-started

---

## 📡 Local Infrared Control

Local IR control was introduced in **Astrion V1.2.0**.

Astrion can transmit IR commands directly through its built-in infrared hardware.

This makes it possible to control traditional AV equipment without requiring the target device itself to be connected to Home Assistant.

The Astrion IR entity can then be used by supported Astrion interfaces such as the TV Card.

For detailed IR configuration:

https://hub.sanytron.com/support/astrion/infrared

---

## 🎬 Harmony and Activity-Style Control

One of the ideas that strongly influenced Astrion is the **Activity** concept introduced by Logitech Harmony.

Instead of thinking about devices individually:

```text
TV
AV Receiver
Media Player
Input
Volume
```

the user can express a higher-level intention:

```text
Watch TV
```

Harmony translated that intention into the required device actions.

Home Assistant allows this idea to go further.

For example:

```text
                WATCH A MOVIE
                      │
                      ▼
               HOME ASSISTANT
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
    Projector         AVR         Player
        │             │             │
        └─────────────┼─────────────┘
                      │
             ┌────────┼────────┐
             ▼        ▼        ▼
          Lights   Curtains  Climate
                      │
                      ▼
                   ASTRION
```

The goal is not simply to put more device controls onto a remote.

It is to provide a physical interface through which users can interact with a much larger Home Assistant system.

This is an important part of the direction behind Astrion.

---

## 🧩 Architecture Principles

Astrion and its software ecosystem follow several design principles.

### Home Assistant Remains the Source of Truth

Device states, services, automations and orchestration remain in Home Assistant.

Astrion does not attempt to replace Home Assistant as the automation engine.

### Physical Interface Instead of Dashboard Mirroring

RosCard does not simply reproduce the entire Home Assistant dashboard on Astrion.

Instead, it selects and presents the relevant functions in a remote-oriented interface.

### Physical + Digital Control

Astrion combines:

* Touchscreen interaction
* Physical buttons
* Home Assistant entities
* Local infrared
* Automation workflows

This allows traditional equipment and modern smart-home devices to coexist within one physical control layer.

### State-Aware Interaction

When supported by the interface and Home Assistant entities, Astrion can react to current device states rather than relying only on static commands.

---

## 🛠️ Current Astrion Software

Astrion continues to evolve through firmware, RosCard and Home Assistant integration updates.

For the latest supported versions and release information:

https://hub.sanytron.com/support/astrion

Current firmware and release notes:

https://hub.sanytron.com/support/astrion/release-notes

---

## 🧪 Development

Astrion Home is developed as part of the broader Astrion ecosystem and evolves through real-world use and community feedback.

We welcome:

* Bug reports
* Feature requests
* Documentation improvements
* Configuration examples
* Testing and feedback
* Pull requests

When reporting an issue, please include:

* Astrion firmware version
* Astrion Home integration version
* Home Assistant version
* Relevant logs
* Configuration details
* Steps to reproduce the issue

Open an issue here:

https://github.com/yyqclhy/Astrion-integration/issues

---

## 🌱 Community-Driven Development

Astrion was designed for Home Assistant users who like to explore, customize and build their own solutions.

We have seen community members create:

* Custom launchers
* APK modifications
* UI experiments
* Button mappings
* RosCard configurations
* Custom integrations
* Automation workflows

We do not see these experiments as something separate from the product.

They are part of how the Astrion ecosystem evolves.

Real-world experimentation often reveals use cases that are difficult to anticipate during initial development, and community feedback has directly influenced subsequent improvements.

Astrion is therefore not only developed **for** the Home Assistant community, but also continues to be developed **with** the community.

---

## 🌐 Sanytron Astrion Resources

### Sanytron Hub

Documentation, downloads, firmware updates, support and product information:

https://hub.sanytron.com/

### Astrion Support Center

Complete Astrion technical documentation:

https://hub.sanytron.com/support/astrion

### Getting Started

https://hub.sanytron.com/support/astrion/getting-started

### Infrared Control

https://hub.sanytron.com/support/astrion/infrared

### Troubleshooting

https://hub.sanytron.com/support/astrion/no-connection

### RosCard

https://github.com/yyqclhy/RosCard

### Sanytron Forum

Technical discussions, troubleshooting, feature requests and community development:

https://forum.sanytron.com/

### Reddit

https://www.reddit.com/r/Sanytron/

### Discord

https://discord.gg/dh2sQrWTH

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

Astrion is built together with its community.

---

## 📄 License

Astrion Home is released under the **MIT License**.

See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgements

Astrion Home builds on the work of the Home Assistant community and the many users who continue to experiment with new ways of interacting with smart homes.

Thank you to everyone who tests releases, reports problems, shares configurations, contributes ideas and helps shape the Astrion ecosystem.

---

<p align="center">
  <strong>Astrion Home</strong><br>
  Home Assistant integration for Astrion IR capabilities<br>
  <em>Part of the Sanytron Astrion ecosystem.</em>
</p>
