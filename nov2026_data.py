"""November 2026 SBU revenue snapshot ? official sub-schedule (actuals to 18 Nov 2026)."""

SHEET_G2G = 679354082.0  # value as printed in the sheet (overstated)
ERP_G2G = 131275374.55    # ERP SBU 77, 1-18 Nov
PERIOD = '1?18 November 2026'
AS_OF = '18 November 2026'
DAYS_ELAPSED = 18
DAYS_IN_MONTH = 30

ROWS = [
    dict(code='', name='G2G (Bongo & MTS & Shipping BADC/BCIC)', head='Mohammad Bahauddin', uom='Service', budget=1319805000.0, forecast=1466450000.0, actual=131275374.55, erp=131275374.55, note='= ERP SBU 77 DyTCL. Sheet value 679,354,082 is a 17-Nov step not supported by ERP.'),
    dict(code='ACCL', name='Akij Cement Company Ltd.', head='Shaibal Shaha', uom='M.Ton', budget=1897000000.0, forecast=1910800000.0, actual=766946653.0, erp=766946653.0, note='ERP SBU 58'),
    dict(code='AIL', name='Akij Ispat Ltd.', head='Shaibal Shaha', uom='M.Ton', budget=1349013300.0, forecast=1253000000.0, actual=574288894.83, erp=574288894.83, note='ERP SBU 102'),
    dict(code='APFIL', name='Akij Poly Fibre Industries Ltd.', head='Badrul Haque', uom='PCS', budget=212362000.0, forecast=212362000.0, actual=83558901.2, erp=83558901.2, note='ERP SBU 19'),
    dict(code='ARMCL', name='Akij Ready Mix Concrete Ltd.', head='Anisur Rahman', uom='CFT', budget=492736942.0, forecast=468750000.0, actual=228407882.13, erp=228407882.13, note='ERP SBU 69'),
    dict(code='ABSL', name='Akij Building Solutions-Asphalt', head='Anisur Rahman', uom='M.Ton', budget=232710000.0, forecast=59000000.0, actual=7677823.0, erp=21060533.31, note='ERP SBU 98 (all ABSL lines)'),
    dict(code='ABSL', name='Akij Building-Lube-Oil', head='Md. Ehtesamul Haq', uom='Ltr', budget=27419473.0, forecast=12500000.0, actual=13382710.31, erp=None, note='within ERP SBU 98'),
    dict(code='', name='Akij Building Solutions-Bitumen', head='Md. Ehtesamul Haq', uom='Ltr', budget=268500000.0, forecast=0.0, actual=0.0, erp=None, note='within ERP SBU 98'),
    dict(code='AEL', name='Akij Essentials Ltd.(Manufacruring)', head='MD Akterrul Alam Shah', uom='M.Ton', budget=1721818163.0, forecast=1436740000.0, actual=866765778.4, erp=None, note='within ERP SBU 36'),
    dict(code='', name='Akij Essentials Ltd.(Export)', head='Md. Abdul Awal', uom='M.Ton', budget=30104918.0, forecast=25000000.0, actual=670096.63, erp=None, note='within ERP SBU 36'),
    dict(code='', name='Akij Essentials Ltd.(Trading)', head='Biju Biswas', uom='M.Ton', budget=2789230975.0, forecast=12381029.0, actual=7367876.21, erp=None, note='within ERP SBU 36'),
    dict(code='BTL', name='Bongo & Daily (Coal)', head='Biju Biswas', uom='M.Ton', budget=1136567000.0, forecast=0.0, actual=508067.0, erp=508067.0, note='ERP SBU 72'),
    dict(code='ACL', name='Akij Commodities Ltd. (Cotton)', head='Bidhan Chandra Pramanik', uom='M.Ton', budget=0.0, forecast=82360861.22, actual=82360861.22, erp=92128100.22, note='ERP SBU 99 (all ACL lines)'),
    dict(code='ACL', name='Akij Commodities Ltd. (F&B)', head='Md. Imran Hossain', uom='Carton', budget=32463550.0, forecast=12000000.0, actual=9760225.0, erp=None, note='within ERP SBU 99'),
    dict(code='', name='Akij Commodities Ltd. (Fruits)', head='Md. Imranul Haque', uom='Carton', budget=0.0, forecast=0.0, actual=7014.0, erp=None, note='within ERP SBU 99'),
    dict(code='ASLL', name='Akij Shipping Line Ltd. (ASLL)', head='MD Rasel Uddin Ahmed', uom='Service', budget=2924602500.0, forecast=2924602500.0, actual=1920147571.0, erp=1333646049.52, note='ERP 6-entity roll-up with FX (PTE x116.127, ASeLLC x32.798)'),
    dict(code='ALEL', name='Akij Light Engineering Ltd.', head='Masud Al Amin Razib', uom='PCS', budget=261318403.0, forecast=273861434.0, actual=126859910.65, erp=126948990.65, note='ERP SBU 114'),
    dict(code='ATL', name='Akij Telecom Ltd.', head='Masud Al Amin Razib', uom='PCS', budget=18000000.0, forecast=3000000.0, actual=1181911.0, erp=1181911.0, note='ERP SBU 118'),
    dict(code='AITL', name='Akij Infotech Ltd.', head='ASM Shawkat Lillat', uom='PCS', budget=49500000.0, forecast=12000000.0, actual=1325450.0, erp=1325450.0, note='ERP SBU 84'),
    dict(code='BPL', name='Blue Pill Limited.', head='Shikdar Maruf Yazdani', uom='PCS', budget=75000000.0, forecast=3000000.0, actual=1665206.5, erp=1665206.5, note='ERP SBU 83'),
    dict(code='iBOS', name='iBOS Limited.', head='Md. Jayed Bin Rashid', uom='Service', budget=27847000.0, forecast=25969000.0, actual=10812528.43, erp=11275613.43, note='ERP SBU 82'),
    dict(code='AAFL', name='Akij Agro Feed Ltd.', head='ATM Habib Ullah', uom='M. Ton', budget=962000000.0, forecast=1119300000.0, actual=691010741.96, erp=691010741.96, note='ERP SBU 109'),
    dict(code='ABL', name='Akij Breeders Ltd.', head='ATM Habib Ullah', uom='PCS', budget=27788270.0, forecast=19485000.0, actual=11762740.0, erp=11762740.0, note='ERP SBU 124'),
    dict(code='NTL', name='Nobayon Traders Ltd.', head='Kazi Sibbir Ahammad', uom='M. Ton', budget=746000000.0, forecast=347000000.0, actual=171949036.0, erp=171949036.0, note='ERP SBU 91'),
    dict(code='AASL', name='Akij Air Service Ltd.', head='Daraz Mhamud', uom='Service', budget=17526671.0, forecast=17526671.0, actual=753542.11, erp=818293.11, note='ERP SBU 122'),
    dict(code='ALL', name='Akij Logistics Ltd.', head='Bikash Bromha', uom='Service', budget=69641900.0, forecast=8473656.74, actual=753542.0, erp=20576329.87, note='ERP SBU 103'),
    dict(code='AMXL', name='Akij Movex Ltd.', head='Md. Shihab Uddin', uom='Service', budget=46000000.0, forecast=46000000.0, actual=4114433.0, erp=4114433.0, note='ERP SBU 128'),
    dict(code='ALCL', name='AKIJ LifeCare Ltd.', head='Istiuck Ali Talukdar', uom='PCS', budget=135895421.0, forecast=92000000.0, actual=52932243.5, erp=52932243.5, note='ERP SBU 116'),
    dict(code='AAIL', name='Akij Automobile Industries Ltd.', head='Md. Ehtesamul Haq', uom='PCS', budget=43897922.0, forecast=43897922.0, actual=23785900.0, erp=23785900.0, note='ERP SBU 115'),
    dict(code='NJL', name='Nextjobz Ltd.', head='Shoeb Hassan', uom='Service', budget=2989000.0, forecast=2989000.0, actual=235284.0, erp=235284.0, note='ERP SBU 129'),
    dict(code='AEFL', name='Akij Electrofab Ltd.', head='Junayed Hafiz', uom='Spool', budget=42003360.0, forecast=5000000.0, actual=1406610.0, erp=1406610.0, note='ERP SBU 120'),
    dict(code='ACEL', name='AKIJ Consumer Electronics Ltd.', head='Abu Tariq Jia Chowdhury', uom='PCS', budget=92747062.0, forecast=17500000.0, actual=6849876.0, erp=6849876.0, note='ERP SBU 126'),
    dict(code='AMPL', name='Akij Mediplex Ltd.', head='Abu Zafor Iqbal Ahamed', uom='Service', budget=10826200.0, forecast=6000000.0, actual=1803808.0, erp=1803808.0, note='ERP SBU 132'),
]

BUDGET_TOTAL = sum(r['budget'] for r in ROWS)
FORECAST_TOTAL = sum(r['forecast'] for r in ROWS)
ACTUAL_TOTAL = sum(r['actual'] for r in ROWS)
ERP_TOTAL = sum(r['erp'] for r in ROWS if r['erp'] is not None)
