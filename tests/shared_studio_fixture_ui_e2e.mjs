import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const base=process.env.STUDIO_BASE||'http://127.0.0.1:3031';
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 const context=await browser.newContext();
 const page=await context.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/?workflow=scenarios%2FS01.json',{waitUntil:'domcontentloaded'});
 const panel=page.getByTestId('procurement-fixture-panel');
 await panel.waitFor({timeout:20000});
 await page.getByTestId('mock-prepare').click();
 await page.getByTestId('mock-progress').waitFor();
 assert.match(await page.getByTestId('mock-progress').innerText(),/0\/13/);
 await page.getByTestId('mock-next').click();
 assert.match(await page.getByTestId('mock-progress').innerText(),/1\/13/);
 await page.getByTestId('mock-run-all').click();
 assert.match(await page.getByTestId('mock-progress').innerText(),/completed · 13\/13/);
 assert.equal(await page.getByText('입출력 확인').count(),13);
 assert.equal(errors.length,0,errors.join(';'));
 // A different scenario is a new mock run, not real production data.
 await page.goto(base+'/?workflow=scenarios%2FS02.json',{waitUntil:'domcontentloaded'});
 await panel.waitFor({timeout:20000});
 await page.getByTestId('mock-prepare').click();
 assert.match(await page.getByTestId('mock-progress').innerText(),/0\/3/);
 await page.getByTestId('mock-stop').click();
 assert.match(await page.getByTestId('mock-progress').innerText(),/stopped/);
 console.log('PROCUREFLOW_MOCK_CHROME_S01_S02_STEPS_AND_STOP_PASS');
 await context.close();
}finally{await browser.close();}
