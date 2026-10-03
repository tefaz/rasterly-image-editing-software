STYLE = """
QWidget { background: #23252a; color: #d2d5dc; font-family: 'Inter', 'Noto Sans', 'Segoe UI', sans-serif; font-size: 12px; }
QMainWindow { background: #1a1b1f; }
QMenuBar { background: #282a2f; padding: 3px 8px; border-bottom: 1px solid #15161a; }
QMenuBar::item { padding: 5px 10px; background: transparent; }
QMenuBar::item:selected { background: #3b3e46; border-radius: 3px; }
QMenu { background: #2c2f35; border: 1px solid #454952; padding: 5px; }
QMenu::item { padding: 7px 30px 7px 14px; border-radius: 3px; }
QMenu::item:selected { background: #414856; }
QMenu::item:disabled { color: #626772; }
QMenu::separator { height: 1px; background: #42454c; margin: 5px 8px; }
QToolButton { border: none; border-radius: 4px; padding: 4px; background: transparent; }
QToolButton:hover { background: #3a3e47; }
QToolButton:checked { background: #444f68; border: 1px solid #687da6; }
QToolButton:disabled { color: #5b606a; }
QPushButton { background: #363a43; border: 1px solid #4b505c; border-radius: 4px; padding: 7px 14px; }
QPushButton:hover { background: #434956; }
QPushButton:pressed { background: #2b303b; }
QPushButton:disabled { color: #606672; border-color: #383c43; }
QPushButton#primary { background: #a7bbf7; color: #171d2d; border-color: #a7bbf7; font-weight: 600; }
QPushButton#primary:hover { background: #bed0ff; }
QPushButton#anchor { padding: 0; }
QPushButton#anchor:checked { background: #485675; border-color: #a7bbf7; }
QLabel { background: transparent; }
QLabel#muted { color: #9096a2; font-size: 11px; }
QLabel#warning { color: #e7b18d; }
QLabel#dialogTitle { font-size: 20px; font-weight: 600; padding-top: 6px; padding-bottom: 8px; }
QLabel#brand { color: #edf0f6; font-weight: 700; font-size: 15px; letter-spacing: 1px; }
QWidget#optionsBar { background: #2c2f35; border-bottom: 1px solid #15161a; }
QWidget#toolsBar { background: #292c32; border-right: 1px solid #16181c; }
QWidget#documentBar { background: #23252a; border-bottom: 1px solid #131519; }
QTabBar#documentTabs { background: #23252a; }
QTabBar#documentTabs::tab { background: #23252a; color: #949cab; padding: 9px 10px 9px 14px; border-right: 1px solid #16181d; border-top: 2px solid transparent; }
QTabBar#documentTabs::tab:selected { background: #30333b; color: #e1e7f2; border-top: 2px solid #94a9e4; }
QTabBar#documentTabs::tab:hover { background: #363b46; }
QTabBar#documentTabs::close-button { subcontrol-position: right; }
QDockWidget#historyDock { background: #272a30; border-left: 1px solid #17191d; }
QDockWidget#historyDock::title { background: #2d3037; padding: 10px; }
QListWidget#historyList { background: #272a30; border: none; outline: none; }
QListWidget#historyList::item { padding: 9px 8px; border-bottom: 1px solid #22252a; }
QListWidget#historyList::item:selected { background: #3a4458; color: #f1f4fc; border-left: 2px solid #a7bbf7; }
QWidget#layersPanel { background: #272a30; border-left: 1px solid #17191d; }
QWidget#panelHeader { background: #2d3037; border-bottom: 1px solid #1c1e23; }
QWidget#panelFooter { background: #292c32; border-top: 1px solid #1c1e23; }
QWidget#documentInfo { background: #272a30; border-top: 1px solid #1c1e23; }
QLabel#infoDimensions { color: #e1e5ee; font-size: 17px; padding: 8px 0; }
QListWidget#layerList { background: #272a30; border: none; outline: none; padding: 5px 0; }
QListWidget#layerList::item { padding: 6px 8px; border-bottom: 1px solid #22252a; }
QListWidget#layerList::item:selected { background: #3a4458; color: #f1f4fc; border-left: 2px solid #a7bbf7; }
QListWidget#layerList::item:hover { background: #333a46; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #1f2228; border: 1px solid #464c58; border-radius: 4px; padding: 6px 9px; selection-background-color: #536d9f; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #a7bbf7; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #292e38; selection-background-color: #465673; border: 1px solid #555d6d; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator, QListWidget::indicator { width: 13px; height: 13px; border: 1px solid #697382; border-radius: 3px; background: #22262e; }
QCheckBox::indicator:checked, QListWidget::indicator:checked { background: #a7bbf7; border: 2px solid #6378a6; }
QStatusBar { background: #24272d; color: #9ba2af; border-top: 1px solid #16181c; }
QStatusBar::item { border: none; }
QDialog { background: #2a2d34; }
QDialogButtonBox { padding-top: 12px; }
QSplitter::handle { background: #17191e; width: 2px; }
QScrollBar:vertical { background: #272a30; width: 8px; }
QScrollBar:horizontal { background: #272a30; height: 12px; }
QScrollBar::handle:horizontal { background: #505865; min-width: 24px; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::handle:vertical { background: #505865; min-height: 20px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #363d4a; color: #f1f4fa; padding: 6px; border: 1px solid #5b667b; }
QProgressBar { background: #1a1e27; border: none; border-radius: 3px; max-height: 4px; }
QProgressBar::chunk { background: #a7bbf7; }
"""
