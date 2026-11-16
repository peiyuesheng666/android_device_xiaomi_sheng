// SPDX-License-Identifier: Apache-2.0
// Keep the standard Recovery menus and rendering; read the board battery
// outside the drawing lock so ADSP startup cannot block the first menu.
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <linux/netlink.h>
#include <poll.h>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <time.h>
#include <unistd.h>

#include "recovery_ui/device.h"
#include "recovery_ui/screen_ui.h"

namespace {
using namespace std::chrono_literals;

bool ReadBatteryCapacity(int32_t* capacity) {
  std::ifstream input("/sys/class/power_supply/battery/capacity");
  std::string text;
  if (!std::getline(input, text)) return false;
  char* end;
  long value = std::strtol(text.c_str(), &end, 10);
  if (end == text.c_str() || *end != '\0' || value < 0 || value > 100) return false;
  *capacity = static_cast<int32_t>(value);
  return true;
}

double BootSeconds() {
  timespec now{};
  clock_gettime(CLOCK_BOOTTIME, &now);
  return now.tv_sec + now.tv_nsec / 1e9;
}

class ShengRecoveryUI : public ScreenRecoveryUI {
 public:
  bool Init(const std::string& locale) override {
    // The base initializer starts its monitor with a five-second retry under
    // updateMutex. Let that thread exit before starting our monitor instead.
    // The flag is protected by ScreenRecoveryUI and is also used at shutdown.
    batt_monitor_thread_stopped_ = true;
    batt_capacity_ = -1;
    if (!ScreenRecoveryUI::Init(locale)) return false;
    if (batt_monitor_thread_.joinable()) batt_monitor_thread_.join();
    batt_monitor_thread_stopped_ = false;
    batt_monitor_thread_ = std::thread(&ShengRecoveryUI::MonitorBattery, this);
    std::printf("I:ShengRecoveryUI initialized at boot %.3fs\n", BootSeconds());
    return true;
  }

  ~ShengRecoveryUI() override {
    // Join both workers before destroying derived state or changing the vtable.
    batt_monitor_thread_stopped_ = true;
    progress_thread_stopped_ = true;
    if (batt_monitor_thread_.joinable()) batt_monitor_thread_.join();
    if (progress_thread_.joinable()) progress_thread_.join();
  }

 protected:
  void draw_battery_capacity_locked() override {
    if (batt_capacity_ >= 0) {
      ScreenRecoveryUI::draw_battery_capacity_locked();
    } else if (menu_) {
      // The percentage is unknown until the real supply exists. Never use
      // the base monitor's fake 100% fallback on a tablet with a battery.
      SetColor(UIElement::INFO);
      int x = ScreenWidth() - margin_width_ * 2 - kMenuIndent - 4 * char_width_;
      DrawTextLine(x, margin_height_, "--%", false);
    }
  }

  void update_screen_locked() override {
    ScreenRecoveryUI::update_screen_locked();
    if (menu_ && !menu_logged_) {
      menu_logged_ = true;
      std::printf("I:ShengRecoveryUI first menu submitted at boot %.3fs\n", BootSeconds());
    }
  }

 private:
  void MonitorBattery() {
    int events = socket(AF_NETLINK, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK,
                        NETLINK_KOBJECT_UEVENT);
    if (events >= 0) {
      sockaddr_nl address{};
      address.nl_family = AF_NETLINK;
      // Recovery's VolumeManager binds its uevent socket to getpid(). A zero
      // port here would claim that same ID before VolumeManager starts, causing
      // its bind to fail and its uninitialized handler to crash on shutdown.
      // This worker's TID is distinct from the main thread's process ID.
      address.nl_pid = static_cast<uint32_t>(gettid());
      address.nl_groups = 1;
      if (bind(events, reinterpret_cast<sockaddr*>(&address), sizeof(address)) < 0) {
        close(events);
        events = -1;
      }
    }
    std::printf("I:ShengRecoveryUI battery events %s at boot %.3fs\n",
                events >= 0 ? "enabled" : "unavailable; using timed reads", BootSeconds());
    bool ready_logged = false;
    auto next_read = std::chrono::steady_clock::now();
    auto earliest_read = next_read;
    while (!batt_monitor_thread_stopped_) {
      if (std::chrono::steady_clock::now() >= next_read) {
        int32_t capacity;
        bool valid = ReadBatteryCapacity(&capacity);
        std::ifstream input("/sys/class/power_supply/battery/status");
        std::string status;
        bool status_valid = static_cast<bool>(std::getline(input, status));
        // All file reads and waits happen outside updateMutex.
        if (valid) {
          std::lock_guard<std::mutex> lock(updateMutex);
          bool charging = status_valid ? status == "Charging" : charging_;
          bool changed = batt_capacity_ != capacity || charging_ != charging;
          batt_capacity_ = capacity;
          charging_ = charging;
          if (changed) {
            update_screen_locked();
            std::printf("I:ShengRecoveryUI battery update %d%% %s at boot %.3fs\n",
                        capacity, status_valid ? status.c_str() : "unknown", BootSeconds());
          }
          if (!ready_logged) {
            ready_logged = true;
            std::printf("I:ShengRecoveryUI real battery %d%% at boot %.3fs\n",
                        capacity, BootSeconds());
          }
        }
        // Timed reads recover from a dropped event; never wait five seconds
        // for a charger transition. Keep the last valid capacity on failure.
        next_read = std::chrono::steady_clock::now() + (valid ? 1s : 100ms);
        earliest_read = std::chrono::steady_clock::now() + 100ms;
      }
      if (events < 0) {
        std::this_thread::sleep_for(100ms);
        continue;
      }
      pollfd descriptor{events, POLLIN, 0};
      if (poll(&descriptor, 1, 100) > 0 && (descriptor.revents & POLLIN)) {
        char buffer[4096];
        bool battery_event = false;
        // Bound draining so a busy producer cannot starve shutdown or redraw.
        for (int i = 0; i < 32; ++i) {
          ssize_t size = recv(events, buffer, sizeof(buffer), MSG_DONTWAIT);
          if (size <= 0) break;
          std::string event(buffer, static_cast<size_t>(size));
          battery_event |= event.find("SUBSYSTEM=power_supply") != std::string::npos ||
                           (event.find("SUBSYSTEM=platform") != std::string::npos &&
                            event.find("battery_charger") != std::string::npos);
        }
        if (battery_event) {
          next_read = std::max(std::chrono::steady_clock::now(), earliest_read);
        }
      }
    }
    if (events >= 0) close(events);
  }

  bool menu_logged_ = false;  // Accessed only with updateMutex held.
};
}  // namespace

Device* make_device() {
  return new Device(new ShengRecoveryUI);
}
