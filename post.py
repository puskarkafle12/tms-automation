import requests

cookies = {
    '_rid': 'eyJlbmMiOiJBMTI4R0NNIiwiYWxnIjoiZGlyIn0..-_izzZBC71Zd3gMD.wefntsYuyhDZnmYaZU57WXbmd8eX3y6ge0Z2jbIdiCb99KUmkdfL-XwyoOMi4Mxi23_VQJJfXP8s4c_AZbG7pWdP-4BCp2SxdKjxdpOAy5sQ5GGgqxHr79ZcwwzoM5Qqa1_phkEocFozXOuJZz8LtNIrt7gfzepV54cqvr85l6yKBopzkKqrk-y0LER9OTIXl2wEZt2YJH_NrrWIbnpuluBD6ORawTzVPxWGNQ1xR3UYUvZdYVXrZG7sWRMMmXAJ1XGzF3Asq-AvnXHg1mgW2a7C9aWalkcS4H9D3xWc5JlzJsykMjrbOTDzyfVuLTFx_hr2tIin7ZlaoMRe8sI0FQnTT_pQKDs8a0HvgmigjHnb7OXQcuYVbKqTJ5MySy7SxZDexkXRYsCaDENB4urWfOYrm078Mbm7SivN2kVu-99LxNcuZgQD876rYLN0YlfqFkxYRZF_2LraN_ocg3hbL-nYDqxUPbc-_EDU5vCmJjcIdWIIYNFELnCSHqMtrlo4yfGoIZxvL6Bk5sBgTKIdKis2xsw0tpl_Sq9h6h-TFKZYsD0R2xVIAXzDYeHgeefBZXJEe3qsJoEE.IQfBFHwrx_kwShogR8_V5A',
    '_aid': 'eyJlbmMiOiJBMTI4R0NNIiwiYWxnIjoiZGlyIn0..tO3HmcqnAt26L2tF.hFVJNFD2kKj5KBMh3NZLBl1nGZjSSxJ6oQLjx6pL0RXsbydlSqxjHKeuLnK1BUQyEmT1_11hsk9NukgY_BF3BGoI5mgj5SYHB6DwcxVWA8O6eGEXjI4PoDP0ow0wANG27kWvwziuPjlXntdSlSzpbMTHgQcYTFjVfODnCSDkcjjWAENSGx65TSB7pZXX_k2ekVwnGDwezA_JebF7Xe23nvpo9cJ6ArAsqsxeLwQ-8Sp53u9vCWxjxDk2ywXHZ27JTUXvo5T1DdyM0egZEDE-M93oOTIdVNYeoDXSTfNP_dca4C6ORgHtkpykznbQ27Qo75RaluJnONdV-3fzeopLQA563xMrPvIelIpRln8F5rh8c68nL9B76rhvcPMmC5pZOhB-JZ87fs09Aq09R-0UU0n8Og2Ou_X5w3KUHmGyWrtcSfYW_XlVLlLU5FSp6NjBnd6-eYzeWquS8sPg8WbIIjTAUmlmMik55rK-OS1Q7DMHx0Ai_eIg9gxO4TgeqTdmqXvTO9w4laqQnXAbeQjSWD96IVj5PL8xQ3T3ymm_GY7Vnytgn8QOyoMRD2sqbz6ELon1xiNdOCJ6.LIl4iFSyHgSd9vaNTvfeaw',
    'XSRF-TOKEN': '621e8793-7c6a-454a-a9f2-b322cd799fc4',
}

headers = {
    'Connection': 'keep-alive',
    'sec-ch-ua': '"Google Chrome";v="95", "Chromium";v="95", ";Not A Brand";v="99"',
    'X-XSRF-TOKEN': '621e8793-7c6a-454a-a9f2-b322cd799fc4',
    'Request-Owner': '36320',
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36',
    'Host-Session-Id': 'TVRJPS1hOWZmNmNhYy0xNDBiLTQ0ZjMtYThhNy0wOTczMzMxZjIxMWU=',
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/plain, */*',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Linux"',
    'Origin': 'https://tms35.nepsetms.com.np',
    'Sec-Fetch-Site': 'same-origin',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Dest': 'empty',
    'Referer': 'https://tms35.nepsetms.com.np/tms/me/memberclientorderentry',
    'Accept-Language': 'en-US,en;q=0.9',
}

data = '{"orderBook":{"orderBookExtensions":[{"orderTypes":{"id":1,"orderTypeCode":"LMT"},"disclosedQuantity":0,"orderValidity":{"id":1,"orderValidityCode":"DAY"},"triggerPrice":0,"orderPrice":474,"orderQuantity":10,"remainingOrderQuantity":10,"marketType":{"id":2,"marketType":"Continuous"}}],"exchange":{"id":1},"dnaConnection":{},"dealer":{},"member":{},"productType":{"id":1,"productCode":"CNC"},"instrumentType":{"id":1,"code":"EQ"},"client":{"activeStatus":"A","id":1974509,"accountType":"CLI","allowedToTrade":"Y","clientMemberCode":"PK479690","clientOrDealer":"C","contactNumber":null,"emailId":null,"notsUniqueClientCode":"201811021236758","clientDealerType":null,"clientGroup":{"activeStatus":"A","id":101,"clientGroupCode":null,"clientGroupName":null},"memberBranch":{"activeStatus":"A","id":1,"branchLocation":null,"branchName":null,"hidden":null,"branchProvince":null,"branchDistrict":null,"branchMunicipality":null,"branchHead":null,"branchPhoneNumber":null},"clientDealerAddressDetails":null,"clientDealerBankDetail":null,"clientDealerIndividual":null,"clientDealerPerTradeLimits":null,"clientDealerProductMappings":null,"clientDealerOrderTypeMappings":null,"clientDealerTradingLimits":null,"clientDepositoryDetail":null,"corporateDetail":null,"corporateOwnershipDetails":null,"displayName":"PUSKAR KAFLE","blockedDate":null,"remarks":null,"parentId":null,"recordType":null,"collateralByEntities":null,"shortSellMode":0,"onlineOrOffline":1,"panNumber":null,"onlineFundTransfer":null,"collateralCalculationMode":1,"isMarginLendingClient":null,"clientRiskType":null,"userAgreementChecked":null,"referredBy":null,"marginLendingClient":null},"security":{"id":357,"exchangeSecurityId":357,"marketProtectionPercentage":0,"divisor":100,"boardLotQuantity":1,"tickSize":0.1},"accountType":1,"cpMemberId":0,"buyOrSell":1},"orderPlacedBy":2,"exchangeOrderId":null}'

response = requests.post('https://tms35.nepsetms.com.np/tmsapi/orderApi/orderbook-v2/', headers=headers, cookies=cookies, data=data)
print(response.status_code)
print(response.json())