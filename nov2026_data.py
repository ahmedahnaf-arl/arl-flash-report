"""November 2026 SBU revenue ? actuals to 22 Nov from the official sub-schedule (Google Sheet),
with ERP cross-check per SBU."""

AS_OF = "22 November 2026"
DAYS_ELAPSED = 22
DAYS_IN_MONTH = 30
PERIOD = "November 1&ndash;22"

ROWS = [
    dict(code='', name='G2G (Bongo & MTS & Shipping BADC/BCIC)', head='Mohammad Bahauddin', uom='Service', budget=1319805000, forecast=1466450000, actual=679354082, erp=174620874.99, sbus=[77]),
    dict(code='ACCL', name='Akij Cement Company Ltd.', head='Shaibal Shaha', uom='M.Ton', budget=1897000000, forecast=1910800000, actual=916675041.25, erp=916675041.25, sbus=[58]),
    dict(code='AIL', name='Akij Ispat Ltd.', head='Shaibal Shaha', uom='M.Ton', budget=1349013300, forecast=1253000000, actual=713207900.23, erp=713207900.23, sbus=[102]),
    dict(code='APFIL', name='Akij Poly Fibre Industries Ltd.', head='Badrul Haque', uom='PCS', budget=212362000, forecast=212362000, actual=104536313.2, erp=104536313.2, sbus=[19]),
    dict(code='ARMCL', name='Akij Ready Mix Concrete Ltd.', head='Anisur Rahman', uom='CFT', budget=492736942, forecast=468750000, actual=268929638.39, erp=268929638.39, sbus=[69]),
    dict(code='ABSL', name='Akij Building Solutions Ltd.', head='Anisur Rahman', uom='M.Ton', budget=528629473, forecast=71718721, actual=22659926.61, erp=22659926.61, sbus=[98]),
    dict(code='AEL', name='Akij Essentials Ltd.', head='MD Akterrul Alam Shah', uom='M.Ton', budget=4541154056, forecast=1474121029, actual=1057048498.91, erp=1057048498.91, sbus=[36]),
    dict(code='BTL', name='Bongo & Daily (Coal)', head='Biju Biswas', uom='M.Ton', budget=1136567000, forecast=0, actual=508067, erp=508067.0, sbus=[72]),
    dict(code='ACL', name='Akij Commodities Ltd.', head='Bidhan Chandra Pramanik', uom='M.Ton', budget=32463550, forecast=94360861.22, actual=92128100.22, erp=92128100.22, sbus=[99]),
    dict(code='ASLL', name='Akij Shipping Line Ltd.', head='MD Rasel Uddin Ahmed', uom='Service', budget=2924602500, forecast=2924602500, actual=3424580468.53, erp=1560839564.93, sbus=[64, 79, 80, 81, 88, 110]),
    dict(code='ALEL', name='Akij Light Engineering Ltd.', head='Masud Al Amin Razib', uom='PCS', budget=261318403, forecast=273861434, actual=156436838.65, erp=156436838.65, sbus=[114]),
    dict(code='ATL', name='Akij Telecom Ltd.', head='Masud Al Amin Razib', uom='PCS', budget=18000000, forecast=3000000, actual=1245188, erp=1245188.0, sbus=[118]),
    dict(code='AITL', name='Akij Infotech Ltd.', head='ASM Shawkat Lillat', uom='PCS', budget=49500000, forecast=12000000, actual=1961650, erp=1961650.0, sbus=[84]),
    dict(code='BPL', name='Blue Pill Limited.', head='Shikdar Maruf Yazdani', uom='PCS', budget=75000000, forecast=3000000, actual=1665206.5, erp=1665206.5, sbus=[83]),
    dict(code='iBOS', name='iBOS Limited.', head='Md. Jayed Bin Rashid', uom='Service', budget=27847000, forecast=25969000, actual=11282326.43, erp=11745411.43, sbus=[82]),
    dict(code='AAFL', name='Akij Agro Feed Ltd.', head='ATM Habib Ullah', uom='M. Ton', budget=962000000, forecast=1119300000, actual=819597190.92, erp=819597190.92, sbus=[109]),
    dict(code='ABL', name='Akij Breeders Ltd.', head='ATM Habib Ullah', uom='PCS', budget=27788270, forecast=19485000, actual=13779460, erp=13779460.0, sbus=[124]),
    dict(code='NTL', name='Nobayon Traders Ltd.', head='Kazi Sibbir Ahammad', uom='M. Ton', budget=746000000, forecast=347000000, actual=186720862.75, erp=186720862.75, sbus=[91]),
    dict(code='AASL', name='Akij Air Service Ltd.', head='Daraz Mhamud', uom='Service', budget=17526671, forecast=17526671, actual=1038448.58, erp=1038448.58, sbus=[122]),
    dict(code='ALL', name='Akij Logistics Ltd.', head='Bikash Bromha', uom='Service', budget=69641900, forecast=8473656.74, actual=10252839.43, erp=31839952.05, sbus=[103]),
    dict(code='AMXL', name='Akij Movex Ltd.', head='Md. Shihab Uddin', uom='Service', budget=46000000, forecast=46000000, actual=18982894, erp=18982894.0, sbus=[128]),
    dict(code='ALCL', name='AKIJ LifeCare Ltd.', head='Istiuck Ali Talukdar', uom='PCS', budget=135895421, forecast=92000000, actual=63127879.14, erp=63127879.14, sbus=[116]),
    dict(code='AAIL', name='Akij Automobile Industries Ltd.', head='Md. Ehtesamul Haq', uom='PCS', budget=43897922, forecast=43897922, actual=26222800, erp=26222800.0, sbus=[115]),
    dict(code='NJL', name='Nextjobz Ltd.', head='Shoeb Hassan', uom='Service', budget=2989000, forecast=2989000, actual=345784, erp=345784.0, sbus=[129]),
    dict(code='AEFL', name='Akij Electrofab Ltd.', head='Junayed Hafiz', uom='Spool', budget=42003360, forecast=5000000, actual=3425610, erp=3425610.0, sbus=[120]),
    dict(code='ACEL', name='AKIJ Consumer Electronics Ltd.', head='Abu Tariq Jia Chowdhury', uom='PCS', budget=92747062, forecast=17500000, actual=7468676, erp=7468676.0, sbus=[126]),
    dict(code='AMPL', name='Akij Mediplex Ltd.', head='Abu Zafor Iqbal Ahamed', uom='Service', budget=10826200, forecast=6000000, actual=1803808, erp=1803808.0, sbus=[132]),
    dict(code='HRML', name='Hashem Rice Mills Ltd. (ERP-only)', head='', uom='', budget=0.0, forecast=0.0, actual=0.0, erp=299298041.97, sbus=[86]),
    dict(code='FAL', name='Fariq Agro Ltd. (ERP-only)', head='', uom='', budget=0.0, forecast=0.0, actual=0.0, erp=39063283.98, sbus=[87]),
    dict(code='AENL', name='Akij Engineering Ltd. (ERP-only)', head='', uom='', budget=0.0, forecast=0.0, actual=0.0, erp=70270.0, sbus=[123]),
]

BUDGET_TOTAL = sum(r["budget"] for r in ROWS)
FORECAST_TOTAL = sum(r["forecast"] for r in ROWS)
ACTUAL_TOTAL = sum(r["actual"] for r in ROWS)
ERP_ONLY = [r for r in ROWS if r["budget"] == 0 and r["actual"] == 0 and r["erp"] > 0]
ERP_ONLY_TOTAL = sum(r["erp"] for r in ERP_ONLY)

