import { createCipheriv } from 'node:crypto';

export function aesEcbPaddedSize(plainSize) {
    const blockSize = 16;
    return plainSize + blockSize - (plainSize % blockSize);
}

export function encryptAesEcb(key, plaintext) {
    const cipher = createCipheriv('aes-128-ecb', key, null);
    return Buffer.concat([cipher.update(plaintext), cipher.final()]);
}
