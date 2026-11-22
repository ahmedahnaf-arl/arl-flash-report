"""November 2026 SBU targets (Budget & Forecast) from the official sub-schedule.

Actuals are fetched live from ERP at build time; only targets are static.
"""

FX_RATES = {80: 116.127, 110: 32.798}  # ASLL-1 posts USD; ASeLLC posts AED -> BDT

TARGETS = [
    dict(code='', name='G2G (Bongo & MTS & Shipping BADC/BCIC)', head='Mohammad Bahauddin', uom='Service', budget=1319805000.0, forecast=1466450000.0, sbus=[77]),
    dict(code='ACCL', name='Akij Cement Company Ltd.', head='Shaibal Shaha', uom='M.Ton', budget=1897000000.0, forecast=1910800000.0, sbus=[58]),
    dict(code='AIL', name='Akij Ispat Ltd.', head='Shaibal Shaha', uom='M.Ton', budget=1349013300.0, forecast=1253000000.0, sbus=[102]),
    dict(code='APFIL', name='Akij Poly Fibre Industries Ltd.', head='Badrul Haque', uom='PCS', budget=212362000.0, forecast=212362000.0, sbus=[19]),
    dict(code='ARMCL', name='Akij Ready Mix Concrete Ltd.', head='Anisur Rahman', uom='CFT', budget=492736942.0, forecast=468750000.0, sbus=[69]),
    dict(code='ABSL', name='Akij Building Solutions Ltd.', head='Anisur Rahman', uom='M.Ton', budget=528629473.0, forecast=71500000.0, sbus=[98]),
    dict(code='AEL', name='Akij Essentials Ltd.', head='MD Akterrul Alam Shah', uom='M.Ton', budget=4541154056.0, forecast=1474121029.0, sbus=[36]),
    dict(code='BTL', name='Bongo & Daily (Coal)', head='Biju Biswas', uom='M.Ton', budget=1136567000.0, forecast=0.0, sbus=[72]),
    dict(code='ACL', name='Akij Commodities Ltd.', head='Bidhan Chandra Pramanik', uom='M.Ton', budget=32463550.0, forecast=94360861.22, sbus=[99]),
    dict(code='ASLL', name='Akij Shipping Line Ltd.', head='MD Rasel Uddin Ahmed', uom='Service', budget=2924602500.0, forecast=2924602500.0, sbus=[64, 79, 80, 81, 88, 110]),
    dict(code='ALEL', name='Akij Light Engineering Ltd.', head='Masud Al Amin Razib', uom='PCS', budget=261318403.0, forecast=273861434.0, sbus=[114]),
    dict(code='ATL', name='Akij Telecom Ltd.', head='Masud Al Amin Razib', uom='PCS', budget=18000000.0, forecast=3000000.0, sbus=[118]),
    dict(code='AITL', name='Akij Infotech Ltd.', head='ASM Shawkat Lillat', uom='PCS', budget=49500000.0, forecast=12000000.0, sbus=[84]),
    dict(code='BPL', name='Blue Pill Limited.', head='Shikdar Maruf Yazdani', uom='PCS', budget=75000000.0, forecast=3000000.0, sbus=[83]),
    dict(code='iBOS', name='iBOS Limited.', head='Md. Jayed Bin Rashid', uom='Service', budget=27847000.0, forecast=25969000.0, sbus=[82]),
    dict(code='AAFL', name='Akij Agro Feed Ltd.', head='ATM Habib Ullah', uom='M. Ton', budget=962000000.0, forecast=1119300000.0, sbus=[109]),
    dict(code='ABL', name='Akij Breeders Ltd.', head='ATM Habib Ullah', uom='PCS', budget=27788270.0, forecast=19485000.0, sbus=[124]),
    dict(code='NTL', name='Nobayon Traders Ltd.', head='Kazi Sibbir Ahammad', uom='M. Ton', budget=746000000.0, forecast=347000000.0, sbus=[91]),
    dict(code='AASL', name='Akij Air Service Ltd.', head='Daraz Mhamud', uom='Service', budget=17526671.0, forecast=17526671.0, sbus=[122]),
    dict(code='ALL', name='Akij Logistics Ltd.', head='Bikash Bromha', uom='Service', budget=69641900.0, forecast=8473656.74, sbus=[103]),
    dict(code='AMXL', name='Akij Movex Ltd.', head='Md. Shihab Uddin', uom='Service', budget=46000000.0, forecast=46000000.0, sbus=[128]),
    dict(code='ALCL', name='AKIJ LifeCare Ltd.', head='Istiuck Ali Talukdar', uom='PCS', budget=135895421.0, forecast=92000000.0, sbus=[116]),
    dict(code='AAIL', name='Akij Automobile Industries Ltd.', head='Md. Ehtesamul Haq', uom='PCS', budget=43897922.0, forecast=43897922.0, sbus=[115]),
    dict(code='NJL', name='Nextjobz Ltd.', head='Shoeb Hassan', uom='Service', budget=2989000.0, forecast=2989000.0, sbus=[129]),
    dict(code='AEFL', name='Akij Electrofab Ltd.', head='Junayed Hafiz', uom='Spool', budget=42003360.0, forecast=5000000.0, sbus=[120]),
    dict(code='ACEL', name='AKIJ Consumer Electronics Ltd.', head='Abu Tariq Jia Chowdhury', uom='PCS', budget=92747062.0, forecast=17500000.0, sbus=[126]),
    dict(code='AMPL', name='Akij Mediplex Ltd.', head='Abu Zafor Iqbal Ahamed', uom='Service', budget=10826200.0, forecast=6000000.0, sbus=[132]),
    dict(code='HRML', name='Hashem Rice Mills Ltd. (ERP-only, no target)', head='', uom='M.Ton', budget=0.0, forecast=0.0, sbus=[86]),
    dict(code='FAL', name='Fariq Agro Ltd. (ERP-only, no target)', head='', uom='M.Ton', budget=0.0, forecast=0.0, sbus=[87]),
    dict(code='AENL', name='Akij Engineering Ltd. (ERP-only, no target)', head='', uom='PCS', budget=0.0, forecast=0.0, sbus=[123]),
]

BUDGET_TOTAL = sum(t["budget"] for t in TARGETS)
FORECAST_TOTAL = sum(t["forecast"] for t in TARGETS)
