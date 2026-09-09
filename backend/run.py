import os
# Allow HTTP for OAuth2 callback (only for local development)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
# Relax OAuthlib scope matching so differences in granted scopes do not raise ScopeChangedError
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
