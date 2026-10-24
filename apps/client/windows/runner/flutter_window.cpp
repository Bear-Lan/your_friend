#include "flutter_window.h"

#include <optional>
#include <algorithm>
#include <shellapi.h>
#include <flutter/standard_method_codec.h>
#include "resource.h"

namespace {
constexpr UINT kTrayMessage = WM_APP + 40;
constexpr UINT kTrayId = 1;
}

#include "flutter/generated_plugin_registrant.h"

FlutterWindow::FlutterWindow(const flutter::DartProject& project)
    : project_(project) {}

FlutterWindow::~FlutterWindow() {}

bool FlutterWindow::OnCreate() {
  if (!Win32Window::OnCreate()) {
    return false;
  }

  RECT frame = GetClientArea();

  // The size here must match the window dimensions to avoid unnecessary surface
  // creation / destruction in the startup path.
  flutter_controller_ = std::make_unique<flutter::FlutterViewController>(
      frame.right - frame.left, frame.bottom - frame.top, project_);
  // Ensure that basic setup of the controller was successful.
  if (!flutter_controller_->engine() || !flutter_controller_->view()) {
    return false;
  }
  RegisterPlugins(flutter_controller_->engine());
  const HWND hwnd = GetHandle();
  SetWindowLongPtr(hwnd, GWL_EXSTYLE,
      GetWindowLongPtr(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_TOOLWINDOW);
  // Exact key pixels become transparent, including hit testing outside the art.
  SetLayeredWindowAttributes(hwnd, RGB(1, 2, 3), 255, LWA_COLORKEY);
  ResizePet(false, true);
  taskbar_created_ = RegisterWindowMessage(L"TaskbarCreated");
  AddTrayIcon();
  channel_ = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      flutter_controller_->engine()->messenger(), "app.yourfriend/desktop",
      &flutter::StandardMethodCodec::GetInstance());
  channel_->SetMethodCallHandler([this](const auto& call, auto result) {
    const auto& method = call.method_name();
    if (method == "setExpanded") {
      const auto* value = call.arguments() ? std::get_if<bool>(call.arguments()) : nullptr;
      if (!value) { result->Error("arguments", "Expected a boolean"); return; }
      ResizePet(*value);
    } else if (method == "beginDrag") {
      ReleaseCapture();
      SendMessage(GetHandle(), WM_NCLBUTTONDOWN, HTCAPTION, 0);
    } else if (method == "showMenu") {
      ShowPetMenu();
    } else {
      result->NotImplemented();
      return;
    }
    result->Success();
  });
  SetChildContent(flutter_controller_->view()->GetNativeWindow());

  flutter_controller_->engine()->SetNextFrameCallback([&]() {
    this->Show();
  });

  // Flutter can complete the first frame before the "show window" callback is
  // registered. The following call ensures a frame is pending to ensure the
  // window is shown. It is a no-op if the first frame hasn't completed yet.
  flutter_controller_->ForceRedraw();

  return true;
}

void FlutterWindow::OnDestroy() {
  NOTIFYICONDATA icon{};
  icon.cbSize = sizeof(icon);
  icon.hWnd = GetHandle();
  icon.uID = kTrayId;
  Shell_NotifyIcon(NIM_DELETE, &icon);
  channel_.reset();
  if (flutter_controller_) {
    flutter_controller_ = nullptr;
  }

  Win32Window::OnDestroy();
}

LRESULT
FlutterWindow::MessageHandler(HWND hwnd, UINT const message,
                              WPARAM const wparam,
                              LPARAM const lparam) noexcept {
  if (taskbar_created_ != 0 && message == taskbar_created_) {
    AddTrayIcon();
    return 0;
  }
  if (message == kTrayMessage) {
    if (lparam == WM_LBUTTONUP) NotifyDart("openChat");
    if (lparam == WM_RBUTTONUP || lparam == WM_CONTEXTMENU) ShowPetMenu();
    return 0;
  }
  if (message == WM_DESTROY) {
    // The base handler clears its HWND before OnDestroy runs.
    NOTIFYICONDATA icon{};
    icon.cbSize = sizeof(icon);
    icon.hWnd = hwnd;
    icon.uID = kTrayId;
    Shell_NotifyIcon(NIM_DELETE, &icon);
  }
  if (message == WM_CLOSE) {
    NotifyDart("collapse");
    return 0;
  }
  if (message == WM_DPICHANGED) {
    const auto* rect = reinterpret_cast<RECT*>(lparam);
    SetWindowPos(hwnd, nullptr, rect->left, rect->top, rect->right - rect->left,
      rect->bottom - rect->top, SWP_NOZORDER | SWP_NOACTIVATE);
    ResizePet(expanded_);
    return 0;
  }
  if (message == WM_DISPLAYCHANGE || message == WM_EXITSIZEMOVE) ResizePet(expanded_);
  // Give Flutter, including plugins, an opportunity to handle window messages.
  if (flutter_controller_) {
    std::optional<LRESULT> result =
        flutter_controller_->HandleTopLevelWindowProc(hwnd, message, wparam,
                                                      lparam);
    if (result) {
      return *result;
    }
  }

  switch (message) {
    case WM_FONTCHANGE:
      flutter_controller_->engine()->ReloadSystemFonts();
      break;
  }

  return Win32Window::MessageHandler(hwnd, message, wparam, lparam);
}

void FlutterWindow::ResizePet(bool expanded, bool initial) {
  const HWND hwnd = GetHandle();
  RECT current{};
  GetWindowRect(hwnd, &current);
  MONITORINFO monitor{sizeof(MONITORINFO)};
  GetMonitorInfo(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), &monitor);
  const double scale = GetDpiForWindow(hwnd) / 96.0;
  const RECT work = monitor.rcWork;
  const int width = std::min(static_cast<int>((expanded ? 420 : 220) * scale),
      static_cast<int>(work.right - work.left));
  const int height = std::min(static_cast<int>((expanded ? 640 : 320) * scale),
      static_cast<int>(work.bottom - work.top));
  const int right = initial ? work.right - static_cast<int>(24 * scale) : current.right;
  const int bottom = initial ? work.bottom - static_cast<int>(16 * scale) : current.bottom;
  const int x = std::clamp(right - width, static_cast<int>(work.left),
      static_cast<int>(work.right) - width);
  const int y = std::clamp(bottom - height, static_cast<int>(work.top),
      static_cast<int>(work.bottom) - height);
  expanded_ = expanded;
  SetWindowPos(hwnd, topmost_ ? HWND_TOPMOST : HWND_NOTOPMOST,
      x, y, width, height, SWP_NOACTIVATE | SWP_FRAMECHANGED);
}

void FlutterWindow::AddTrayIcon() {
  NOTIFYICONDATA icon{};
  icon.cbSize = sizeof(icon);
  icon.hWnd = GetHandle();
  icon.uID = kTrayId;
  icon.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
  icon.uCallbackMessage = kTrayMessage;
  icon.hIcon = LoadIcon(GetModuleHandle(nullptr), MAKEINTRESOURCE(IDI_APP_ICON));
  wcscpy_s(icon.szTip, L"your friend - yf");
  Shell_NotifyIcon(NIM_ADD, &icon);
}

void FlutterWindow::NotifyDart(const char* method) {
  ShowWindow(GetHandle(), SW_SHOWNORMAL);
  SetForegroundWindow(GetHandle());
  if (channel_) channel_->InvokeMethod(method, nullptr);
}

void FlutterWindow::ShowPetMenu() {
  HMENU menu = CreatePopupMenu();
  AppendMenu(menu, MF_STRING, 1, L"打开聊天");
  AppendMenu(menu, MF_STRING, 2, L"收回桌宠");
  AppendMenu(menu, MF_STRING, 3, L"衣橱");
  AppendMenu(menu, MF_STRING, 4, L"设置");
  AppendMenu(menu, MF_STRING | (topmost_ ? MF_CHECKED : MF_UNCHECKED), 5, L"始终置顶");
  AppendMenu(menu, MF_SEPARATOR, 0, nullptr);
  AppendMenu(menu, MF_STRING, 6, L"退出 your friend");
  POINT position{};
  GetCursorPos(&position);
  SetForegroundWindow(GetHandle());
  const UINT command = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON,
      position.x, position.y, 0, GetHandle(), nullptr);
  DestroyMenu(menu);
  if (command == 1) NotifyDart("openChat");
  if (command == 2) NotifyDart("collapse");
  if (command == 3) NotifyDart("wardrobe");
  if (command == 4) NotifyDart("settings");
  if (command == 5) { topmost_ = !topmost_; ResizePet(expanded_); }
  if (command == 6) DestroyWindow(GetHandle());
  PostMessage(GetHandle(), WM_NULL, 0, 0);
}
