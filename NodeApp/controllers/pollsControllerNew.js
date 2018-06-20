const formidable = require('formidable');
const PythonShell = require('python-shell');
const url = require('url');
const sleep = require('sleep');
const fs = require('fs');
const redis = require('redis');
const options = {
    mode:'text',
    pythonPath: '/usr/bin/python3.5',
    pythonOptions:['-u']
};

/*
* State has 4 values:
* 1. OPEN
* 2. CLOSED
* 3. RUN
* 4. COMPLETED
*/

exports.openForRegistration = function (req, res)
{
    if(isNaN(req.session.state))
    {
        req.session.state = "OPEN";
        req.session.pollName = req.params.pollName;
    }

    res.redirect('/polls');
};

exports.registerToPoll = function (req, res) {
    let pollName = req.session.pollName;
    let clientIp = req.params.ip;
    let type = req.params.type;

    let client = redis.createClient();

    // insert ip address to addresses table
    client.rpush('addresses', clientIp, function (err) {
        if (err) console.log("Error in address registration");
    });

    client.rpush(pollName, clientIp.toString(), type.toString(),
        function (err) {
        if(err) console.log("Error in registration");
    });
    res.redirect('/polls');
};

exports.getPollsParams = function (req, res) {
    let ip = req.params.ip;
    let jsonData = {};
    let counter = 0;
    let client = redis.createClient();
    client.lrange('execution', 0, -1, function (err, data) {
        for (let idx = 0; idx < data.length; idx+=20)
        {
            counter++;
            if(data[idx] === ip)
            {
                for(let idx2 = idx + 1; idx2 < 19; idx2+=2)
                jsonData[data[idx2]] = data[idx2 + 1];
            }
        }
    });

    let circuitName = 'ArythmeticVarianceFor3InputsAnd' + counter + 'Parties.txt';
    jsonData['circuitFileAddress'] =  __dirname + '/../public/assets/' + circuitName;

    res.json(JSON.stringify(jsonData));
};

exports.changePollState = function (req, res) {

};

exports.closePollForRegistration = function (req, res) {
    req.session.state = "CLOSED";
    let pollName = req.params.pollName ;
    let client = redis.createClient();

    let numberOfMobiles = 0;
    let mobilesIps = [];
    let idx = 0;
    client.lrange(pollName, 0, -1, function (err, data) {
        if (err) console.log('Error retrieve poll data');
        for (idx = 0; idx < data.length; idx += 2)
        {
            if (data[idx] === 'online_mobile')
            {
                let mobileIp = data[idx + 1];
                client.lrem('addresses', 0, mobileIp, function (err) {
                    if(err) console.log("Error removing mobile ip");
                });

                mobilesIps.push(mobileIp);
                numberOfMobiles += 1;
            }
        }
    });

    let partiesSize = 0;
    client.lrange('addresses', 0, -1, function (err, data) {
        if (err) console.log('Error retrieve addresses');

        //write addresses to file
        let fileName = __dirname + '/../public/assets/parties.conf';
        //delete file if exists
        fs.unlink(fileName, function (err) {console.log(err)});

        if(numberOfMobiles > 0)
        {
            for(let idx = 0; idx < numberOfMobiles; idx++)
            {
                fs.appendFileSync(fileName, '34.239.19.87:' + (9000 + idx * 100).toString());
            }
        }
        let offlineUsers = [];

        data.forEach(function (entry) {
            fs.appendFileSync(fileName, entry + ":8000\n");
            partiesSize += 1;
            offlineUsers.push(entry);
        });

        partiesSize += numberOfMobiles;

        let exec = require('child_process').exec;
        let createCircuit = 'java -jar ' + __dirname + '/../public/assets/GenerateArythmeticCircuitForVariance.jar '
            + partiesSize + ' 3';
        exec(createCircuit, function (error, stdout){
            if(error) console.log('Error: ' + error);
            console.log(stdout);
        });
        sleep(10);
        //copy the circuit to the public path
        let circuitName = 'ArythmeticVarianceFor3InputsAnd' + partiesSize + 'Parties.txt'
        let copyCommand = 'cp ' + __dirname + ' ' + circuitName + ' ' + __dirname + '/../public/assets/';
        exec(copyCommand, function (error, stdout) {
            if(error) console.log('Error: ' + error);
            console.log(stdout);
        });

         // for each entry save the exact cli parameters

    for(let mobilesIdx = 0; mobilesIdx < numberOfMobiles; mobilesIdx++)
    {
        client.rpush('execution', mobilesIps[mobilesIdx], pollName, '-partyID', mobilesIdx, '-partiesNumber',
            partiesSize, '-inputFile', 'inputSalary' + mobilesIdx + '.txt', '-outputFile', 'output.txt', '-circuitFile',
            circuitName, '-proxyAddress', '34.239.19.87', '-fieldType', 'ZpMersenne', '-internalIterationsNumber', '1',
            '-NG', '1', function (err) {console.log(err)});
    }

    for(let offlineIdx = 0; offlineIdx < offlineUsers.length; offlineIdx++)
    {
        client.rpush('execution', offlineUsers[offlineIdx], pollName, '-partyID', offlineIdx, '-partiesNumber',
            partiesSize, '-inputFile', 'inputSalary' + offlineIdx + '.txt', '-outputFile', 'output.txt', '-circuitFile',
            circuitName, '-partiesFile', 'parties.conf', '-fieldType', 'ZpMersenne', '-internalIterationsNumber', '1',
            '-NG', '1', function (err) {console.log(err)});
    }
    });


    res.redirect('/polls')
};