'use strict';
/* 옷 꾸러미 서명 도구(ed25519) — 공개판 전용 키.
   node tools/pack_sign.js keygen <비밀키.pem>               키가 없을 때만 새로 만듦(있으면 그대로). 화면에는 공개키만 찍음
   node tools/pack_sign.js pubkey <비밀키.pem>               공개키(raw 32바이트 base64) — pet/packs.js 의 PUBKEYS 에 넣는 값
   node tools/pack_sign.js sign <비밀키.pem> <파일>           파일 바이트에 서명 → 서명 base64 한 줄(표준출력)
   node tools/pack_sign.js verify <공개키 base64> <파일> <서명 base64>   맞으면 '맞음' + 종료 코드 0
   비밀키 파일은 저장소 밖에 둔다(저장소의 공개 전 검사가 pem 파일을 막음). 비밀키 값은 어디에도 찍지 않는다. */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const [cmd, a, b, c] = process.argv.slice(2);
const rawPub = key => Buffer.from(crypto.createPublicKey(key).export({ format: 'jwk' }).x, 'base64url').toString('base64');
const loadKey = f => crypto.createPrivateKey(fs.readFileSync(f));

if (cmd === 'keygen') {
  if (!a) { console.error('비밀키 파일 경로가 필요해요'); process.exit(2); }
  if (!fs.existsSync(a)) {
    fs.mkdirSync(path.dirname(a), { recursive: true });
    const { privateKey } = crypto.generateKeyPairSync('ed25519');
    fs.writeFileSync(a, privateKey.export({ format: 'pem', type: 'pkcs8' }), { mode: 0o600, flag: 'wx' });
    console.log('새 키 만듦');
  } else console.log('키 있음(그대로 둠)');
  console.log('공개키 ' + rawPub(loadKey(a)));
} else if (cmd === 'pubkey') {
  console.log(rawPub(loadKey(a)));
} else if (cmd === 'sign') {
  process.stdout.write(crypto.sign(null, fs.readFileSync(b), loadKey(a)).toString('base64') + '\n');
} else if (cmd === 'verify') {
  const pub = crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: Buffer.from(a, 'base64').toString('base64url') }, format: 'jwk' });
  const ok = crypto.verify(null, fs.readFileSync(b), pub, Buffer.from(c, 'base64'));
  console.log(ok ? '맞음' : '틀림');
  process.exit(ok ? 0 : 1);
} else {
  console.error('쓰는 법: keygen | pubkey | sign | verify');
  process.exit(2);
}
