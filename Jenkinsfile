/*
 * SPDX-License-Identifier: GPL-2.0+
 */
import groovy.json.*

// 'global' var to store git info
def scmVars

// Greenwave RPM dependencies
def installDepsCmd = '''
sudo dnf -y install \
    python3-dogpile-cache \
    python3-fedmsg \
    python3-flask \
    python3-prometheus_client \
    python3-PyYAML \
    python3-requests
'''.trim()

try { // massive try{} catch{} around the entire build for failure notifications

timestamps {
node('fedora-28') {
    checkout scm
    scmVars.GIT_AUTHOR_EMAIL = sh (
        script: 'git --no-pager show -s --format=\'%ae\'',
        returnStdout: true
    ).trim()

    sh """
    ${installDepsCmd}
    sudo dnf -y install python3-flake8 python3-pylint python3-sphinx \
        python3-sphinxcontrib-httpdomain python3-pytest-cov
    """
    stage('Build Docs') {
        sh '''
        sudo dnf install -y \
            python3-sphinx \
            python3-sphinxcontrib-httpdomain \
            python3-sphinxcontrib-issuetracker
        '''
        sh 'make -C docs html'
        archiveArtifacts artifacts: 'docs/_build/html/**'
    }
    if (scmVars.GIT_BRANCH == 'origin/master') {
        stage('Publish Docs') {
            sshagent (credentials: ['pagure-greenwave-deploy-key']) {
                sh '''
                mkdir -p ~/.ssh/
                touch ~/.ssh/known_hosts
                ssh-keygen -R pagure.io
                echo 'pagure.io,140.211.169.204 ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC198DWs0SQ3DX0ptu+8Wq6wnZMrXUCufN+wdSCtlyhHUeQ3q5B4Hgto1n2FMj752vToCfNTn9mWO7l2rNTrKeBsELpubl2jECHu4LqxkRVihu5UEzejfjiWNDN2jdXbYFY27GW9zymD7Gq3u+T/Mkp4lIcQKRoJaLobBmcVxrLPEEJMKI4AJY31jgxMTnxi7KcR+U5udQrZ3dzCn2BqUdiN5dMgckr4yNPjhl3emJeVJ/uhAJrEsgjzqxAb60smMO5/1By+yF85Wih4TnFtF4LwYYuxgqiNv72Xy4D/MGxCqkO/nH5eRNfcJ+AJFE7727F7Tnbo4xmAjilvRria/+l' >>~/.ssh/known_hosts
                rm -rf docs-on-pagure
                git clone ssh://git@pagure.io/docs/odcs.git docs-on-pagure
                rm -r docs-on-pagure/*
                cp -r docs/_build/html/* docs-on-pagure/
                cd docs-on-pagure
                git add -A .
                if [[ "$(git diff --cached --numstat | wc -l)" -eq 0 ]] ; then
                    exit 0 # No changes, nothing to commit
                fi
                git config user.name "Jenkins Job"
                git config user.email "nobody@redhat.com"
                git commit -m 'Automatic commit of docs built by Jenkins job ${env.JOB_NAME} #${env.BUILD_NUMBER}'
                git push origin master
                '''
            }
        }
    }
}


} // end of timestamps
} catch (e) {
    // since the result isn't set until after the pipeline script runs, we must set it here if it fails
    currentBuild.result = 'FAILURE'
    throw e
} finally {

}
