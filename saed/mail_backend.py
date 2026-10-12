import smtplib
import ssl

from django.core.mail.backends.smtp import EmailBackend as DjangoSMTPBackend


class EmailBackend(DjangoSMTPBackend):
    """SMTP backend compatible with Python 3.12+ on older Django (no keyfile/certfile)."""

    def open(self):
        if self.connection:
            return False
        try:
            ctx = ssl.create_default_context()
            if self.use_ssl:
                self.connection = smtplib.SMTP_SSL(
                    self.host, self.port, timeout=self.timeout, context=ctx
                )
            else:
                self.connection = smtplib.SMTP(
                    self.host, self.port, timeout=self.timeout
                )
                if self.use_tls:
                    self.connection.ehlo()
                    self.connection.starttls(context=ctx)
                    self.connection.ehlo()
            if self.username and self.password:
                self.connection.login(self.username, self.password)
            return True
        except OSError:
            if not self.fail_silently:
                raise

