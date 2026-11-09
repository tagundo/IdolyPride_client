package game.qualiarts.idolypride.localserver;

import java.security.GeneralSecurityException;
import javax.crypto.Cipher;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/** AES primitive for the embedded Python codec, which owns PKCS#7 padding. */
public final class CryptoBridge {
    private CryptoBridge() { }

    public static byte[] aesCbc(boolean encrypt, byte[] key, byte[] iv, byte[] payload)
            throws GeneralSecurityException {
        Cipher cipher = Cipher.getInstance("AES/CBC/NoPadding");
        cipher.init(encrypt ? Cipher.ENCRYPT_MODE : Cipher.DECRYPT_MODE,
                new SecretKeySpec(key, "AES"), new IvParameterSpec(iv));
        return cipher.doFinal(payload);
    }
}
