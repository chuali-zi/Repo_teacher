function mountApp() {
  const { App } = window.RTV3;
  if (!App) {
    window.setTimeout(mountApp, 0);
    return;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(<App />);
}

mountApp();
